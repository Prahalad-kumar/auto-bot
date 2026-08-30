"""Tick-driven Kite market-data service.

KiteTicker delivers ticks asynchronously. We cache the latest tick in Redis,
publish events for the UI, and build completed 5-minute underlying candles.
The service never polls Kite every millisecond; it reacts to every tick Kite
actually sends.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import redis
from kiteconnect import KiteTicker

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import AuditLog, BrokerConnection, Order, Position, Signal, Trade
from app.services.market_data.candles import CandleBuilder
from app.services.backtest.engine import _crosses_above, _crosses_below, _ema_series, _macd_series

log = logging.getLogger("autobot.realtime")
IST = ZoneInfo(settings.MARKET_TIMEZONE)
INDEX_SYMBOLS = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
}


class RealtimeMarketService:
    def __init__(self) -> None:
        self.redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.ticker: KiteTicker | None = None
        self.instrument_tokens: dict[int, str] = {}
        self.builders = {name: CandleBuilder(5) for name in INDEX_SYMBOLS}
        self.candles: dict[str, list] = {name: [] for name in INDEX_SYMBOLS}
        self._subscribed = set()
        self.option_tokens: dict[int, str] = {}
        self.nfo_cache: list[dict] = []

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, name="kite-realtime", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        try:
            if self.ticker:
                self.ticker.close()
        except Exception:
            log.exception("Error closing KiteTicker")

    def _publish(self, event: dict) -> None:
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        try:
            self.redis.set("autobot:market:last_event", json.dumps(event), ex=30)
            self.redis.publish("autobot:events", json.dumps(event, default=str))
        except Exception:
            log.exception("Redis publish failed")

    def _load_index_tokens(self) -> dict[int, str]:
        db = SessionLocal()
        try:
            c = db.query(BrokerConnection).filter(BrokerConnection.broker == "ZERODHA").first()
            if not c or c.status != "CONNECTED" or not c.access_token:
                return {}
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=settings.KITE_API_KEY)
            kite.set_access_token(c.access_token)
            instruments = kite.instruments("NSE")
            result = {}
            for name, qualified in INDEX_SYMBOLS.items():
                symbol = qualified.split(":", 1)[1]
                row = next((x for x in instruments if x.get("tradingsymbol") == symbol), None)
                if row:
                    result[int(row["instrument_token"])] = name
            return result
        finally:
            db.close()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                if not settings.KITE_API_KEY:
                    time.sleep(15)
                    continue
                tokens = self._load_index_tokens()
                if not tokens:
                    time.sleep(10)
                    continue
                self.instrument_tokens = tokens
                db = SessionLocal()
                try:
                    c = db.query(BrokerConnection).filter(BrokerConnection.broker == "ZERODHA").first()
                    access_token = c.access_token if c and c.status == "CONNECTED" else None
                finally:
                    db.close()
                if not access_token:
                    time.sleep(10)
                    continue
                self._connect(access_token, list(tokens))
            except Exception:
                log.exception("Realtime market-data loop failed")
                time.sleep(5)

    def _seed_history(self, kite, token_map: dict[int, str]) -> None:
        """Warm the 5m index candle buffers once after a websocket connects."""
        today = datetime.now(IST).date()
        for token, underlying in token_map.items():
            try:
                rows = kite.historical_data(token, today, today, "5minute")
                for row in rows:
                    self.candles[underlying].append(__import__("app.services.market_data.candles", fromlist=["Candle"]).Candle(
                        timestamp=row["date"], open=float(row["open"]), high=float(row["high"]),
                        low=float(row["low"]), close=float(row["close"]), volume=int(row.get("volume") or 0),
                        oi=row.get("oi"), instrument_token=token, tradingsymbol=underlying))
                self.candles[underlying] = self.candles[underlying][-200:]
            except Exception:
                log.exception("Could not seed %s candles", underlying)

    def _paper_entry(self, underlying: str, direction: str, candle_time, spot: float) -> tuple[int, str] | None:
        if settings.TRADING_MODE != "PAPER":
            return None
        db = SessionLocal()
        try:
            if db.query(Position).filter(Position.status == "OPEN").count() >= settings.MAX_OPEN_POSITIONS:
                return None
            trades_today = db.query(Trade).filter(Trade.timestamp >= datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)).count()
            if trades_today >= settings.MAX_TRADES_PER_DAY:
                return None
            if not self.nfo_cache:
                from kiteconnect import KiteConnect
                c = db.query(BrokerConnection).filter(BrokerConnection.broker == "ZERODHA").first()
                if not c or not c.access_token:
                    return None
                kc = KiteConnect(api_key=settings.KITE_API_KEY); kc.set_access_token(c.access_token)
                self.nfo_cache = [x for x in kc.instruments("NFO") if x.get("instrument_type") in {"CE", "PE"} and x.get("name") == underlying]
            contracts = self.nfo_cache
            if not contracts:
                return None
            expiry = min(x["expiry"] for x in contracts)
            contracts = [x for x in contracts if x["expiry"] == expiry and x.get("instrument_type") == direction]
            if not contracts:
                return None
            contract = min(contracts, key=lambda x: abs(float(x["strike"]) - spot))
            token = int(contract["instrument_token"]); symbol = contract["tradingsymbol"]
            from kiteconnect import KiteConnect
            c = db.query(BrokerConnection).filter(BrokerConnection.broker == "ZERODHA").first()
            kc = KiteConnect(api_key=settings.KITE_API_KEY); kc.set_access_token(c.access_token)
            quote_key = f"NFO:{symbol}"
            quote = kc.ltp(quote_key).get(quote_key, {})
            price = float(quote.get("last_price") or 0)
            if price <= 0:
                return None
            idem = f"{underlying}:{direction}:{candle_time.isoformat()}"
            lock_key = f"autobot:signal:{idem}"
            if not self.redis.set(lock_key, "1", nx=True, ex=86400):
                return None
            qty = int(contract.get("lot_size") or 1)
            if qty > settings.MAX_QUANTITY or price * qty > settings.MAX_ORDER_VALUE:
                return None
            stop = round(price * 0.90, 2); target = round(price * 1.20, 2)
            signal = Signal(strategy_id=1, action="BUY", underlying=underlying, option_type=direction, strike=float(contract["strike"]), reason="EMA 5/10 crossover with MACD 8/16/3 confirmation within 2 completed candles", timestamp=candle_time)
            order = Order(client_order_id=f"PAPER-{idem.replace(':','-')}", symbol=symbol, side="BUY", quantity=qty, price=price, status="COMPLETE", mode="PAPER")
            position = Position(symbol=symbol, underlying=underlying, quantity=qty, average_price=price, stop_loss=stop, target=target, status="OPEN")
            db.add_all([signal, order, position])
            db.add(AuditLog(event="PAPER_ORDER_EXECUTED", entity="position", entity_id=symbol, metadata_json={"underlying": underlying, "option_type": direction, "strike": contract["strike"], "entry_price": price, "quantity": qty, "stop_loss": stop, "target": target}))
            db.commit()
            self.option_tokens[token] = symbol
            self._publish({"type":"paper_order","event":"PAPER_ORDER_EXECUTED","underlying":underlying,"symbol":symbol,"option_type":direction,"strike":contract["strike"],"price":price,"quantity":qty})
            return token, symbol
        except Exception:
            db.rollback(); log.exception("Paper entry failed")
            return None
        finally:
            db.close()

    def _monitor_paper_option(self, token: int, price: float, timestamp: datetime) -> None:
        if settings.TRADING_MODE != "PAPER" or price <= 0:
            return
        db = SessionLocal()
        try:
            position = db.query(Position).filter(Position.symbol == self.option_tokens.get(token), Position.status == "OPEN").first()
            if not position:
                return
            position.unrealized_pnl = round((price - position.average_price) * position.quantity, 2)
            reason = None
            exit_price = price
            if position.stop_loss is not None and price <= position.stop_loss:
                reason, exit_price = "STOP_LOSS", position.stop_loss
            elif position.target is not None and price >= position.target:
                reason, exit_price = "TARGET", position.target
            if reason:
                gross = round((exit_price - position.average_price) * position.quantity, 2)
                trade = Trade(strategy="NIFTY 5m EMA/MACD ATM", symbol=position.symbol, entry_price=position.average_price, exit_price=exit_price, quantity=position.quantity, gross_pnl=gross, charges=0, net_pnl=gross, execution_mode="PAPER", entry_reason="Confirmed underlying setup", exit_reason=reason, timestamp=timestamp)
                position.status = "CLOSED"; position.realized_pnl = gross; position.unrealized_pnl = 0
                db.add(trade); db.add(AuditLog(event="PAPER_POSITION_CLOSED", entity="position", entity_id=position.symbol, metadata_json={"exit_reason":reason,"exit_price":exit_price,"pnl":gross})); db.commit()
                self._publish({"type":"paper_exit","event":"PAPER_POSITION_CLOSED","symbol":position.symbol,"price":exit_price,"pnl":gross,"reason":reason})
            else:
                db.commit()
                self._publish({"type":"pnl","symbol":position.symbol,"unrealized_pnl":position.unrealized_pnl,"price":price})
        finally:
            db.close()

    def _connect(self, access_token: str, tokens: list[int]) -> None:
        self.ticker = KiteTicker(settings.KITE_API_KEY, access_token)

        def on_connect(ws, response):
            self._subscribed = set(tokens)
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_FULL, tokens)
            try:
                from kiteconnect import KiteConnect
                kc = KiteConnect(api_key=settings.KITE_API_KEY); kc.set_access_token(access_token)
                self._seed_history(kc, self.instrument_tokens)
            except Exception:
                log.exception("History warm-up failed")
            self._publish({"type": "system", "event": "MARKET_DATA_CONNECTED", "tokens": tokens})

        def on_ticks(ws, ticks):
            for tick in ticks:
                token = int(tick.get("instrument_token"))
                underlying = self.instrument_tokens.get(token)
                if not underlying and token in self.option_tokens:
                    ts = tick.get("exchange_timestamp") or tick.get("timestamp") or datetime.now(timezone.utc)
                    if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
                    self._monitor_paper_option(token, float(tick.get("last_price") or 0), ts.astimezone(IST))
                    self._publish({"type":"option_tick","instrument_token":token,"symbol":self.option_tokens[token],"last_price":float(tick.get("last_price") or 0)})
                    continue
                if not underlying:
                    continue
                ts = tick.get("exchange_timestamp") or tick.get("timestamp") or datetime.now(timezone.utc)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                ts_ist = ts.astimezone(IST)
                normalized = {
                    "type": "tick",
                    "instrument_token": token,
                    "tradingsymbol": underlying,
                    "underlying": underlying,
                    "timestamp": ts_ist.isoformat(),
                    "last_price": float(tick.get("last_price") or 0),
                    "volume": int(tick.get("volume_traded") or tick.get("volume") or 0),
                    "oi": tick.get("oi"),
                }
                self.redis.set(f"autobot:tick:{token}", json.dumps(normalized), ex=10)
                self._publish(normalized)
                completed = self.builders[underlying].update(normalized)
                if completed:
                    self.candles[underlying].append(completed)
                    self.candles[underlying] = self.candles[underlying][-200:]
                    if len(self.candles[underlying]) >= 20:
                        rows = self.candles[underlying]
                        closes = [float(c.close) for c in rows]
                        ema5, ema10 = _ema_series(closes, 5), _ema_series(closes, 10)
                        macd, macd_signal = _macd_series(closes, 8, 16, 3)
                        i = len(rows) - 1
                        bullish = any(_crosses_above(ema5, ema10, j) for j in range(max(1, i-2), i+1)) and any(_crosses_above(macd, macd_signal, j) for j in range(max(1, i-2), i+1))
                        bearish = any(_crosses_below(ema5, ema10, j) for j in range(max(1, i-2), i+1)) and any(_crosses_below(macd, macd_signal, j) for j in range(max(1, i-2), i+1))
                        if bullish or bearish:
                            direction = "CE" if bullish else "PE"
                            entry = self._paper_entry(underlying, direction, completed.timestamp, completed.close)
                            if entry:
                                option_token, _ = entry
                                try: ws.subscribe([option_token]); ws.set_mode(ws.MODE_FULL, [option_token])
                                except Exception: log.exception("Could not subscribe to paper option")

                    self._publish({
                        "type": "candle",
                        "underlying": underlying,
                        "timeframe": "5m",
                        "timestamp": completed.timestamp.isoformat(),
                        "open": completed.open,
                        "high": completed.high,
                        "low": completed.low,
                        "close": completed.close,
                        "volume": completed.volume,
                    })

        def on_close(ws, code, reason):
            self._publish({"type": "system", "event": "MARKET_DATA_DISCONNECTED", "code": code, "reason": reason})

        def on_error(ws, code, reason):
            self._publish({"type": "system", "event": "MARKET_DATA_ERROR", "code": code, "reason": reason})

        self.ticker.on_connect = on_connect
        self.ticker.on_ticks = on_ticks
        self.ticker.on_close = on_close
        self.ticker.on_error = on_error
        self.ticker.connect(threaded=False)


service = RealtimeMarketService()

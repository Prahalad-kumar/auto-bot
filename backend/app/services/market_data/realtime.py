"""Real-time KiteTicker -> Redis event bridge and paper execution loop.

The service is event driven: it processes each tick received from KiteTicker.
It deliberately does not poll the Kite HTTP quote endpoint for every tick.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import redis
from kiteconnect import KiteTicker

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import AuditLog, BrokerConnection, Order, Position, Signal
from app.services.market_data.candles import Candle, CandleBuilder
from app.services.backtest.engine import _crosses_above, _crosses_below, _ema_series, _macd_series

IST = ZoneInfo(settings.MARKET_TIMEZONE)
EVENT_CHANNEL = "autobot:events"
TICK_PREFIX = "autobot:tick:"
UNDERLYINGS = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
}


def _publish(r: redis.Redis, event_type: str, payload: dict) -> None:
    message = json.dumps({"type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(), **payload}, default=str)
    r.publish(EVENT_CHANNEL, message)


class LiveMarketDataService:
    """Single-process KiteTicker manager used by the FastAPI instance."""

    def __init__(self) -> None:
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ticker: KiteTicker | None = None
        self._connected_token: str | None = None
        self._subscribed: set[int] = set()
        self._builders: dict[int, CandleBuilder] = {}
        self._history: dict[int, list[Candle]] = {}
        self._symbols: dict[int, str] = {}
        self._option_tokens: set[int] = set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="kite-market-data", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            if self._ticker:
                try:
                    self._ticker.close()
                except Exception:
                    pass

    def _get_token(self) -> str | None:
        db = SessionLocal()
        try:
            c = db.query(BrokerConnection).filter(BrokerConnection.broker == "ZERODHA").first()
            if c and c.status == "CONNECTED" and c.access_token:
                return c.access_token
            return None
        finally:
            db.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            token = self._get_token()
            if not token or not settings.KITE_API_KEY:
                time.sleep(5)
                continue
            if token == self._connected_token and self._ticker is not None:
                time.sleep(5)
                continue
            try:
                self._connect(token)
            except Exception as exc:
                try:
                    _publish(self.redis, "system", {"status": "ERROR", "message": f"KiteTicker connection failed: {exc}"})
                except Exception:
                    pass
                time.sleep(5)

    def _connect(self, access_token: str) -> None:
        self._connected_token = access_token
        ticker = KiteTicker(settings.KITE_API_KEY, access_token)
        self._ticker = ticker

        def on_connect(ws, response):
            db = SessionLocal()
            try:
                instruments = ws._instrument_tokens if hasattr(ws, "_instrument_tokens") else []
                if not instruments:
                    kite_instruments = self._http_instruments(access_token)
                    tokens = []
                    for name, key in UNDERLYINGS.items():
                        symbol = key.split(":", 1)[1]
                        item = next((x for x in kite_instruments if x.get("exchange") == "NSE" and x.get("tradingsymbol") == symbol), None)
                        if item:
                            token_int = int(item["instrument_token"])
                            self._symbols[token_int] = name
                            self._builders[token_int] = CandleBuilder(5)
                            self._history[token_int] = []
                            tokens.append(token_int)
                    if tokens:
                        ws.subscribe(tokens)
                        ws.set_mode(ws.MODE_FULL, tokens)
                        self._subscribed.update(tokens)
                _publish(self.redis, "system", {"status": "CONNECTED", "message": "KiteTicker connected"})
            finally:
                db.close()

        def on_ticks(ws, ticks):
            for tick in ticks:
                self._handle_tick(tick)

        def on_close(ws, code, reason):
            _publish(self.redis, "system", {"status": "DISCONNECTED", "message": f"KiteTicker closed: {code} {reason}"})
            self._ticker = None

        def on_error(ws, code, reason):
            _publish(self.redis, "system", {"status": "ERROR", "message": f"KiteTicker error: {code} {reason}"})

        ticker.on_connect = on_connect
        ticker.on_ticks = on_ticks
        ticker.on_close = on_close
        ticker.on_error = on_error
        ticker.connect(threaded=False, disable_ssl_verification=False, reconnect=True, reconnect_max_tries=50, reconnect_max_delay=60)

    def _http_instruments(self, access_token: str) -> list[dict]:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=settings.KITE_API_KEY)
        kite.set_access_token(access_token)
        return kite.instruments("NSE")

    def _handle_tick(self, tick: dict) -> None:
        token = int(tick.get("instrument_token"))
        ts = tick.get("exchange_timestamp") or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        normalized = {
            "instrument_token": token,
            "timestamp": ts.isoformat(),
            "last_price": float(tick.get("last_price") or 0),
            "volume": int(tick.get("volume_traded") or tick.get("volume") or 0),
            "oi": tick.get("oi"),
            "tradingsymbol": self._symbols.get(token),
        }
        self.redis.setex(f"{TICK_PREFIX}{token}", 30, json.dumps(normalized, default=str))
        _publish(self.redis, "tick", normalized)

        builder = self._builders.get(token)
        if builder:
            candle = builder.update({**normalized, "timestamp": ts.astimezone(IST)})
            if candle:
                history = self._history.setdefault(token, [])
                history.append(candle)
                del history[:-120]
                _publish(self.redis, "candle", {"underlying": self._symbols[token], "candle": candle.__dict__})
                if len(history) >= 20:
                    self._evaluate_strategy(self._symbols[token], history)
        elif token in self._option_tokens:
            self._monitor_option_position(token, float(tick.get("last_price") or 0))

    def subscribe_option(self, token: int, symbol: str) -> None:
        with self._lock:
            self._symbols[token] = symbol
            self._option_tokens.add(token)
            if self._ticker and token not in self._subscribed:
                self._ticker.subscribe([token])
                self._ticker.set_mode(self._ticker.MODE_FULL, [token])
                self._subscribed.add(token)

    def _evaluate_strategy(self, underlying: str, candles: list[Candle]) -> None:
        # Only evaluate on the just-closed candle; the current forming candle is never used.
        completed = candles[:-1]
        if len(completed) < 20:
            return
        closes = [c.close for c in completed]
        ema5, ema10 = _ema_series(closes, 5), _ema_series(closes, 10)
        macd, signal = _macd_series(closes, 8, 16, 3)
        end = len(completed) - 1
        window = range(max(1, end - 2), end + 1)
        bullish = any(_crosses_above(ema5, ema10, i) for i in window) and any(_crosses_above(macd, signal, i) for i in window)
        bearish = any(_crosses_below(ema5, ema10, i) for i in window) and any(_crosses_below(macd, signal, i) for i in window)
        if not (bullish or bearish):
            return
        direction = "CE" if bullish else "PE"
        db = SessionLocal()
        try:
            if db.query(Position).filter(Position.underlying == underlying, Position.status == "OPEN").first():
                return
            candle_time = completed[-1].timestamp
            if db.query(Signal).filter(Signal.underlying == underlying, Signal.timestamp == candle_time).first():
                return
            from kiteconnect import KiteConnect
            c = db.query(BrokerConnection).filter(BrokerConnection.broker == "ZERODHA").first()
            if not c or not c.access_token:
                return
            kite = KiteConnect(api_key=settings.KITE_API_KEY)
            kite.set_access_token(c.access_token)
            spot_key = UNDERLYINGS[underlying]
            spot = float(kite.ltp(spot_key)[spot_key]["last_price"])
            contracts = [x for x in kite.instruments("NFO") if x.get("name") == underlying and x.get("instrument_type") == direction]
            if not contracts:
                return
            expiry = min(x["expiry"] for x in contracts)
            contracts = [x for x in contracts if x["expiry"] == expiry]
            contract = min(contracts, key=lambda x: abs(float(x["strike"]) - spot))
            symbol = contract["tradingsymbol"]
            price = float(kite.ltp(f"NFO:{symbol}")[f"NFO:{symbol}"]["last_price"])
            qty = int(contract["lot_size"])
            reason = f"{underlying} index 5m EMA 5/10 + MACD 8/16/3 confirmation"
            signal = Signal(strategy_id=1, action="BUY", underlying=underlying, option_type=direction, strike=float(contract["strike"]), reason=reason, timestamp=candle_time)
            db.add(signal)
            db.add(Order(client_order_id=f"PAPER-{candle_time.isoformat()}-{underlying}-{direction}", symbol=symbol, side="BUY", quantity=qty, price=price, status="COMPLETE", mode="PAPER"))
            db.add(Position(symbol=symbol, underlying=underlying, quantity=qty, average_price=price, stop_loss=round(price * .9, 2), target=round(price * 1.2, 2), status="OPEN"))
            db.add(AuditLog(event="PAPER_ORDER_EXECUTED", entity="position", entity_id=symbol, metadata_json={"underlying": underlying, "option_type": direction, "strike": float(contract["strike"]), "entry_price": price, "quantity": qty, "stop_loss": round(price * .9, 2), "target": round(price * 1.2, 2)}))
            db.commit()
            self.subscribe_option(int(contract["instrument_token"]), symbol)
            _publish(self.redis, "signal", {"underlying": underlying, "action": "BUY", "option_type": direction, "strike": float(contract["strike"]), "symbol": symbol, "price": price, "quantity": qty, "reason": reason})
            _publish(self.redis, "order", {"status": "COMPLETE", "mode": "PAPER", "symbol": symbol, "price": price, "quantity": qty})
        finally:
            db.close()

    def _monitor_option_position(self, token: int, price: float) -> None:
        db = SessionLocal()
        try:
            symbol = self._symbols.get(token)
            if not symbol:
                return
            position = db.query(Position).filter(Position.symbol == symbol, Position.status == "OPEN").first()
            if not position:
                return
            reason = "TARGET" if price >= (position.target or float("inf")) else "STOP_LOSS" if price <= (position.stop_loss or float("-inf")) else None
            position.unrealized_pnl = round((price - position.average_price) * position.quantity, 2)
            if reason:
                gross = position.unrealized_pnl
                position.realized_pnl = gross
                position.status = "CLOSED"
                db.add(__import__("app.models", fromlist=["Trade"]).Trade(strategy="AUTO", symbol=symbol, entry_price=position.average_price, exit_price=price, quantity=position.quantity, gross_pnl=gross, charges=0, net_pnl=gross, execution_mode="PAPER", entry_reason="Automated paper setup", exit_reason=reason))
                db.add(AuditLog(event="PAPER_POSITION_CLOSED", entity="position", entity_id=symbol, metadata_json={"exit_price": price, "reason": reason, "pnl": gross}))
                db.commit()
                _publish(self.redis, "position", {"symbol": symbol, "status": "CLOSED", "exit_price": price, "reason": reason, "pnl": gross})
            else:
                db.commit()
                _publish(self.redis, "position", {"symbol": symbol, "status": "OPEN", "price": price, "unrealized_pnl": position.unrealized_pnl})
        finally:
            db.close()


_service: LiveMarketDataService | None = None

def get_market_data_service() -> LiveMarketDataService:
    global _service
    if _service is None:
        _service = LiveMarketDataService()
    return _service

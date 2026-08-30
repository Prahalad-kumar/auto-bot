"""Paper-only live market monitor. It never calls Kite order-placement APIs."""
from datetime import datetime, time
from zoneinfo import ZoneInfo
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AuditLog, Order, Position, Signal
from app.services.backtest.engine import _crosses_above, _crosses_below, _ema_series, _macd_series

IST = ZoneInfo("Asia/Kolkata")
UNDERLYINGS = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK"}


def market_is_open(now: datetime | None = None) -> bool:
    now = now or datetime.now(IST)
    if now.weekday() > 4:
        return False
    return time.fromisoformat(settings.MARKET_OPEN) <= now.time() < time.fromisoformat(settings.MARKET_CLOSE)


def _signal_direction(rows: list[dict]) -> str | None:
    """Use only the last completed candles; MACD and EMA crosses must be within 2 bars."""
    closes = [float(row["close"]) for row in rows[:-1]]
    if len(closes) < 20:
        return None
    ema5, ema10 = _ema_series(closes, 5), _ema_series(closes, 10)
    macd, macd_signal = _macd_series(closes, 8, 16, 3)
    end = len(closes)
    ema_up = [i for i in range(max(1, end - 3), end) if _crosses_above(ema5, ema10, i)]
    macd_up = [i for i in range(max(1, end - 3), end) if _crosses_above(macd, macd_signal, i)]
    ema_down = [i for i in range(max(1, end - 3), end) if _crosses_below(ema5, ema10, i)]
    macd_down = [i for i in range(max(1, end - 3), end) if _crosses_below(macd, macd_signal, i)]
    if any(abs(a - b) <= 2 for a in ema_up for b in macd_up):
        return "CE"
    if any(abs(a - b) <= 2 for a in ema_down for b in macd_down):
        return "PE"
    return None


def evaluate_paper_markets(db: Session, kite) -> list[dict]:
    if settings.TRADING_MODE != "PAPER" or not market_is_open():
        return []
    events = []
    instruments = kite.instruments("NFO")
    nse_instruments = kite.instruments("NSE")
    for underlying, spot_key in UNDERLYINGS.items():
        spot_symbol = spot_key.split(":", 1)[1]
        spot_instrument = next((item for item in nse_instruments if item.get("tradingsymbol") == spot_symbol), None)
        if not spot_instrument:
            continue
        candles = kite.historical_data(int(spot_instrument["instrument_token"]), datetime.now(IST).date(), datetime.now(IST).date(), "5minute")
        direction = _signal_direction(candles)
        if not direction or db.query(Position).filter(Position.underlying == underlying, Position.status == "OPEN").first():
            continue
        signal_time = candles[-2]["date"]
        if db.query(Signal).filter(Signal.underlying == underlying, Signal.timestamp == signal_time).first():
            continue
        spot = float(kite.ltp(spot_key)[spot_key]["last_price"])
        contracts = [item for item in instruments if item.get("name") == underlying and item.get("instrument_type") == direction]
        expiry = min(item["expiry"] for item in contracts)
        contracts = [item for item in contracts if item["expiry"] == expiry]
        contract = min(contracts, key=lambda item: abs(float(item["strike"]) - spot))
        symbol = contract["tradingsymbol"]
        price = float(kite.ltp(f"NFO:{symbol}")[f"NFO:{symbol}"]["last_price"])
        quantity = int(contract["lot_size"])
        reason = f"{underlying} EMA 5/10 crossover and MACD 8/16/3 confirmation within 2 completed candles"
        signal = Signal(strategy_id=1, action="BUY", underlying=underlying, option_type=direction, strike=float(contract["strike"]), reason=reason, timestamp=signal_time)
        db.add(signal)
        db.add(Order(client_order_id=f"PAPER-{uuid.uuid4().hex}", symbol=symbol, side="BUY", quantity=quantity, price=price, status="COMPLETE", mode="PAPER"))
        db.add(Position(symbol=symbol, underlying=underlying, quantity=quantity, average_price=price, stop_loss=round(price * .9, 2), target=round(price * 1.2, 2), status="OPEN"))
        db.add(AuditLog(event="PAPER_ORDER_EXECUTED", entity="position", entity_id=symbol, metadata_json={"underlying": underlying, "option_type": direction, "lot_size": quantity, "entry_price": price, "capital_required": round(price * quantity, 2), "stop_loss": round(price * .9, 2), "target": round(price * 1.2, 2), "signal_time": signal_time.isoformat()}))
        events.append({"underlying": underlying, "symbol": symbol, "option_type": direction, "price": price, "quantity": quantity})
    db.commit()
    return events

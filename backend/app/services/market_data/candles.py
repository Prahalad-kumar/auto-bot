from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    oi: int | None = None
    instrument_token: int | None = None
    tradingsymbol: str | None = None

class CandleBuilder:
    def __init__(self, timeframe_minutes=5):
        self.timeframe = timeframe_minutes
        self.current = None

    def update(self, tick: dict):
        ts = tick["timestamp"]
        bucket_minute = (ts.minute // self.timeframe) * self.timeframe
        bucket = ts.replace(minute=bucket_minute, second=0, microsecond=0)
        price = float(tick["last_price"])
        if self.current is None or self.current.timestamp != bucket:
            old = self.current
            self.current = Candle(bucket, price, price, price, price, int(tick.get("volume") or 0), tick.get("oi"), tick.get("instrument_token"), tick.get("tradingsymbol"))
            return old
        c = self.current
        self.current = Candle(c.timestamp, c.open, max(c.high, price), min(c.low, price), price, int(tick.get("volume") or c.volume), tick.get("oi"), c.instrument_token, c.tradingsymbol)
        return None

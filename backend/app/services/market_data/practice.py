"""Offline practice helpers; never connects to a broker or places an order."""
from datetime import datetime, timezone


def sample_tick(price: float = 100.0) -> dict:
    return {
        "instrument_token": 0,
        "tradingsymbol": "PRACTICE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "last_price": float(price),
        "volume": 0,
        "oi": None,
    }

from dataclasses import dataclass
from datetime import datetime, time
from app.core.config import settings

@dataclass
class RiskDecision:
    approved: bool
    reason: str

class RiskManager:
    def validate(self, *, quantity: int, order_value: float, daily_pnl: float, open_positions: int, trades_today: int, market_open: bool, data_fresh: bool, broker_healthy: bool):
        checks = [
            (quantity <= settings.MAX_QUANTITY, "maximum quantity exceeded"),
            (order_value <= settings.MAX_ORDER_VALUE, "maximum order value exceeded"),
            (daily_pnl > -abs(settings.MAX_DAILY_LOSS), "maximum daily loss exceeded"),
            (open_positions < settings.MAX_OPEN_POSITIONS, "maximum open positions reached"),
            (trades_today < settings.MAX_TRADES_PER_DAY, "maximum trades per day reached"),
            (market_open, "market session is closed"),
            (data_fresh, "market data is stale"),
            (broker_healthy, "broker connection is unhealthy"),
        ]
        for ok, reason in checks:
            if not ok:
                return RiskDecision(False, reason)
        return RiskDecision(True, "approved")

import uuid
from .base import Broker, OrderResult
from app.core.config import settings

class LiveTradingDisabledError(RuntimeError):
    pass

class ZerodhaBroker(Broker):
    def __init__(self, kite):
        self.kite = kite

    def _guard_live(self):
        if settings.TRADING_MODE != "LIVE" or not settings.LIVE_TRADING_ENABLED:
            raise LiveTradingDisabledError("Real order execution requires TRADING_MODE=LIVE and LIVE_TRADING_ENABLED=true")

    def place_order(self, symbol, side, quantity, price=None):
        self._guard_live()
        order_type = "LIMIT" if price is not None else "MARKET"
        transaction = self.kite.TRANSACTION_TYPE_BUY if side.upper() == "BUY" else self.kite.TRANSACTION_TYPE_SELL
        oid = self.kite.place_order(
            variety=self.kite.VARIETY_REGULAR,
            exchange=settings.DEFAULT_EXCHANGE,
            tradingsymbol=symbol,
            transaction_type=transaction,
            quantity=quantity,
            order_type=order_type,
            product=self.kite.PRODUCT_MIS,
            price=price,
        )
        return OrderResult(f"LIVE-{uuid.uuid4().hex}", str(oid), "OPEN", None)

    def cancel_order(self, broker_order_id):
        self._guard_live()
        self.kite.cancel_order(self.kite.VARIETY_REGULAR, order_id=broker_order_id)

    def positions(self):
        self._guard_live()
        return self.kite.positions()

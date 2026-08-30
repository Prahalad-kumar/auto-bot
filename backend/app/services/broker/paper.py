import uuid
from .base import Broker, OrderResult

class PaperBroker(Broker):
    def __init__(self, initial_capital: float = 100000):
        self.cash = initial_capital
        self.orders = {}
    def place_order(self, symbol, side, quantity, price=None):
        client_id = f"PAPER-{uuid.uuid4().hex}"
        fill = float(price or 0)
        self.orders[client_id] = {"symbol": symbol, "side": side, "quantity": quantity, "price": fill}
        return OrderResult(client_id, None, "COMPLETE", fill)
    def cancel_order(self, broker_order_id):
        return None
    def positions(self):
        return []

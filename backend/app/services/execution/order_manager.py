import uuid
from app.services.risk.manager import RiskManager

class OrderManager:
    def __init__(self, broker, risk=None):
        self.broker = broker
        self.risk = risk or RiskManager()
        self.seen = set()

    def submit(self, signal: dict, quantity: int, price: float | None, risk_kwargs: dict):
        client_key = signal.get("idempotency_key") or uuid.uuid4().hex
        if client_key in self.seen:
            raise RuntimeError("duplicate order prevented")
        decision = self.risk.validate(quantity=quantity, order_value=(price or 0)*quantity, **risk_kwargs)
        if not decision.approved:
            raise RuntimeError(f"risk rejected: {decision.reason}")
        self.seen.add(client_key)
        return self.broker.place_order(signal["symbol"], signal["action"], quantity, price)

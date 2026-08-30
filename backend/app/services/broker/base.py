from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class OrderResult:
    client_order_id: str
    broker_order_id: str | None
    status: str
    average_price: float | None = None

class Broker(ABC):
    @abstractmethod
    def place_order(self, symbol: str, side: str, quantity: int, price: float | None = None) -> OrderResult: ...
    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> None: ...
    @abstractmethod
    def positions(self) -> list[dict]: ...

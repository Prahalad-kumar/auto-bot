from datetime import datetime
from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class StrategyCreate(BaseModel):
    name: str
    config: dict

class SignalSchema(BaseModel):
    strategy_id: str
    timestamp: datetime
    underlying: str
    action: str
    option_type: str | None = None
    strike: float | None = None
    reason: str
    confidence: float | None = None

class OrderRequest(BaseModel):
    symbol: str
    side: str
    quantity: int = Field(gt=0)
    price: float | None = None

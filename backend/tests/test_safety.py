import pytest
from app.services.broker.zerodha import ZerodhaBroker, LiveTradingDisabledError
from app.services.risk.manager import RiskManager

def test_live_guard(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "TRADING_MODE", "PAPER")
    monkeypatch.setattr(config.settings, "LIVE_TRADING_ENABLED", False)
    class K: pass
    with pytest.raises(LiveTradingDisabledError):
        ZerodhaBroker(K()).place_order("X","BUY",1)

def test_risk_rejects_daily_loss(monkeypatch):
    r=RiskManager()
    d=r.validate(quantity=1,order_value=10,daily_pnl=-1000,open_positions=0,trades_today=0,market_open=True,data_fresh=True,broker_healthy=True)
    assert not d.approved

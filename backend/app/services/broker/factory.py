from app.core.config import settings
from .paper import PaperBroker
from .zerodha import ZerodhaBroker

def get_broker(kite=None):
    if settings.TRADING_MODE == "PAPER":
        return PaperBroker(settings.PAPER_INITIAL_CAPITAL)
    if settings.TRADING_MODE == "LIVE":
        if kite is None:
            raise RuntimeError("Zerodha client is required for LIVE mode")
        return ZerodhaBroker(kite)
    raise RuntimeError("Backtest uses its own simulator and cannot obtain a live broker")

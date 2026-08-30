from app.workers.celery_app import celery_app

@celery_app.task
def health_task():
    return {"status":"ok"}

@celery_app.task
def monitor_paper_market_task():
    """Scheduled PAPER monitor; it only reads Kite market data and persists simulations."""
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.models import BrokerConnection
    from app.services.execution.paper_monitor import evaluate_paper_markets
    if settings.TRADING_MODE != "PAPER":
        return {"status": "skipped", "reason": "not paper mode"}
    db = SessionLocal()
    try:
        connection = db.query(BrokerConnection).filter(BrokerConnection.broker == "ZERODHA").first()
        if not connection or connection.status != "CONNECTED" or not connection.access_token:
            return {"status": "skipped", "reason": "kite disconnected"}
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=settings.KITE_API_KEY)
        kite.set_access_token(connection.access_token)
        return {"status": "ok", "events": evaluate_paper_markets(db, kite)}
    finally:
        db.close()

@celery_app.task
def run_backtest_task(strategy_config, candles):
    from app.services.strategy.engine import StrategyEngine
    from app.services.backtest.engine import BacktestEngine
    return BacktestEngine().run(candles, StrategyEngine(strategy_config)).__dict__

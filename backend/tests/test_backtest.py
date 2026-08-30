from datetime import datetime, timedelta, timezone

from app.services.backtest.engine import BacktestEngine
from app.services.market_data.candles import Candle


def test_backtest_requires_enough_completed_candles():
    now = datetime.now(timezone.utc)
    candles = [Candle(now, 100, 101, 99, 100)] * 19
    try:
        BacktestEngine().run(candles, candles)
    except ValueError as exc:
        assert "20" in str(exc)
    else:
        raise AssertionError("short datasets must not backtest")


def test_backtest_returns_metrics_without_future_data():
    start = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)
    underlying, options = [], []
    for index in range(30):
        timestamp = start + timedelta(minutes=5 * index)
        price = 100 + index
        underlying.append(Candle(timestamp, price, price + 1, price - 1, price))
        options.append(Candle(timestamp, 100, 101, 99, 100, tradingsymbol="NIFTY26JAN100CE"))
    result = BacktestEngine().run(underlying, options)
    assert result["summary"]["initial_capital"] == 100000
    assert "equity_curve" in result

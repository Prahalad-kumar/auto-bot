from dataclasses import asdict, dataclass
from math import sqrt
from typing import Iterable

from app.services.market_data.candles import Candle


@dataclass
class BacktestTrade:
    side: str
    option_type: str
    symbol: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    quantity: int
    capital_required: float
    stop_loss: float
    target: float
    exit_reason: str
    gross_pnl: float
    charges: float
    net_pnl: float


def _ema_series(values: list[float], length: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < length:
        return result
    value = sum(values[:length]) / length
    result[length - 1] = value
    alpha = 2 / (length + 1)
    for index in range(length, len(values)):
        value = alpha * values[index] + (1 - alpha) * value
        result[index] = value
    return result


def _macd_series(values: list[float], fast: int = 8, slow: int = 16, signal: int = 3) -> tuple[list[float | None], list[float | None]]:
    fast_values, slow_values = _ema_series(values, fast), _ema_series(values, slow)
    line: list[float | None] = [None] * len(values)
    compact: list[float] = []
    indexes: list[int] = []
    for index, (fast_value, slow_value) in enumerate(zip(fast_values, slow_values)):
        if fast_value is not None and slow_value is not None:
            line[index] = fast_value - slow_value
            compact.append(line[index])
            indexes.append(index)
    signal_compact = _ema_series(compact, signal)
    signal_values: list[float | None] = [None] * len(values)
    for index, value in zip(indexes, signal_compact):
        signal_values[index] = value
    return line, signal_values


def _crosses_above(left: list[float | None], right: list[float | None], index: int) -> bool:
    return index > 0 and None not in (left[index - 1], right[index - 1], left[index], right[index]) and left[index - 1] <= right[index - 1] and left[index] > right[index]


def _crosses_below(left: list[float | None], right: list[float | None], index: int) -> bool:
    return index > 0 and None not in (left[index - 1], right[index - 1], left[index], right[index]) and left[index - 1] >= right[index - 1] and left[index] < right[index]


class BacktestEngine:
    """Completed-candle backtest for the confirmed NIFTY EMA/MACD option strategy."""

    def run(self, underlying: Iterable[Candle], options: Iterable[Candle], *, initial_capital: float = 100000, quantity: int = 1, stop_percent: float = 10, target_percent: float = 20, charge_per_order: float = 0) -> dict:
        underlying = sorted(underlying, key=lambda candle: candle.timestamp)
        option_by_time = {candle.timestamp: candle for candle in options}
        if len(underlying) < 20:
            raise ValueError("At least 20 completed NIFTY 5-minute candles are required")
        if quantity < 1 or stop_percent <= 0 or target_percent <= 0:
            raise ValueError("Quantity, stop loss, and target must be positive")
        closes = [candle.close for candle in underlying]
        ema5, ema10 = _ema_series(closes, 5), _ema_series(closes, 10)
        macd, macd_signal = _macd_series(closes)
        ema_up = [_crosses_above(ema5, ema10, i) for i in range(len(underlying))]
        ema_down = [_crosses_below(ema5, ema10, i) for i in range(len(underlying))]
        macd_up = [_crosses_above(macd, macd_signal, i) for i in range(len(underlying))]
        macd_down = [_crosses_below(macd, macd_signal, i) for i in range(len(underlying))]
        trades: list[BacktestTrade] = []
        active: dict | None = None
        equity = initial_capital
        equity_curve = [{"timestamp": underlying[0].timestamp.isoformat(), "equity": equity}]

        for i in range(1, len(underlying)):
            option = option_by_time.get(underlying[i].timestamp)
            if active and option:
                stop_hit = option.low <= active["stop"]
                target_hit = option.high >= active["target"]
                if stop_hit or target_hit:
                    # A single OHLC bar cannot prove the intrabar sequence; protect
                    # the backtest from optimistic bias by prioritising the stop.
                    exit_price = active["stop"] if stop_hit else active["target"]
                    gross = (exit_price - active["entry"]) * quantity
                    charges = charge_per_order * 2
                    net = gross - charges
                    equity += net
                    trades.append(BacktestTrade(active["side"], active["option_type"], option.tradingsymbol or "OPTION", active["time"].isoformat(), option.timestamp.isoformat(), active["entry"], exit_price, quantity, round(active["entry"] * quantity, 2), active["stop"], active["target"], "STOP_LOSS" if stop_hit else "TARGET", gross, charges, net))
                    active = None
            if active is None and i + 1 < len(underlying):
                lookback = range(max(1, i - 2), i + 1)
                bullish = any(ema_up[j] for j in lookback) and any(macd_up[j] for j in lookback) and any(abs(a - b) <= 2 for a in [j for j in lookback if ema_up[j]] for b in [j for j in lookback if macd_up[j]])
                bearish = any(ema_down[j] for j in lookback) and any(macd_down[j] for j in lookback) and any(abs(a - b) <= 2 for a in [j for j in lookback if ema_down[j]] for b in [j for j in lookback if macd_down[j]])
                if bullish or bearish:
                    entry_candle = option_by_time.get(underlying[i + 1].timestamp)
                    required_type = "CE" if bullish else "PE"
                    if entry_candle and (entry_candle.tradingsymbol or "").upper().endswith(required_type):
                        entry = entry_candle.open
                        active = {"side": "BUY", "option_type": required_type, "entry": entry, "stop": entry * (1 - stop_percent / 100), "target": entry * (1 + target_percent / 100), "time": entry_candle.timestamp}
            equity_curve.append({"timestamp": underlying[i].timestamp.isoformat(), "equity": round(equity, 2)})
        if active:
            final = option_by_time.get(underlying[-1].timestamp)
            if final:
                gross = (final.close - active["entry"]) * quantity
                charges = charge_per_order * 2
                net = gross - charges
                equity += net
                trades.append(BacktestTrade(active["side"], active["option_type"], final.tradingsymbol or "OPTION", active["time"].isoformat(), final.timestamp.isoformat(), active["entry"], final.close, quantity, round(active["entry"] * quantity, 2), active["stop"], active["target"], "END_OF_DATA", gross, charges, net))
        net_values = [trade.net_pnl for trade in trades]
        wins = [value for value in net_values if value > 0]
        losses = [value for value in net_values if value < 0]
        peak, max_drawdown = initial_capital, 0.0
        for point in equity_curve:
            peak = max(peak, point["equity"])
            max_drawdown = min(max_drawdown, point["equity"] - peak)
        return {"summary": {"initial_capital": initial_capital, "final_capital": round(equity, 2), "net_pnl": round(equity - initial_capital, 2), "return_percent": round((equity / initial_capital - 1) * 100, 2), "trades": len(trades), "winning_trades": len(wins), "losing_trades": len(losses), "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0, "average_win": round(sum(wins) / len(wins), 2) if wins else 0, "average_loss": round(sum(losses) / len(losses), 2) if losses else 0, "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else None, "max_drawdown": round(max_drawdown, 2)}, "trades": [asdict(trade) for trade in trades], "equity_curve": equity_curve}

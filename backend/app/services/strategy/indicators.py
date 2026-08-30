import numpy as np

def sma(values, length):
    return np.mean(values[-length:]) if len(values) >= length else None

def ema(values, length):
    if len(values) < length: return None
    alpha = 2 / (length + 1)
    value = float(np.mean(values[:length]))
    for x in values[length:]:
        value = alpha * float(x) + (1-alpha) * value
    return value

def rsi(values, length=14):
    if len(values) <= length: return None
    d = np.diff(values)
    gains = np.maximum(d, 0)
    losses = np.maximum(-d, 0)
    avg_gain = np.mean(gains[-length:])
    avg_loss = np.mean(losses[-length:])
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100/(1+rs))

def atr(highs, lows, closes, length=14):
    if len(closes) < length + 1: return None
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
    return float(np.mean(trs[-length:]))

def vwap(highs, lows, closes, volumes):
    if not volumes or sum(volumes) == 0: return None
    typical = (np.array(highs)+np.array(lows)+np.array(closes))/3
    return float(np.sum(typical*np.array(volumes))/np.sum(volumes))

def macd(values, fast=12, slow=26, signal=9):
    if len(values) < slow + signal: return None
    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)
    if fast_ema is None or slow_ema is None: return None
    # Compact terminal MACD implementation; strategy configs can replace/extend this.
    line = fast_ema - slow_ema
    return {"macd": line, "signal": None}

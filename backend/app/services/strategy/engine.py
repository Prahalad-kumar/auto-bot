from .indicators import sma, ema, rsi, atr, vwap, macd
from .rules import evaluate

class StrategyEngine:
    def __init__(self, config: dict):
        self.config = config

    def indicators(self, candles):
        closes=[c.close for c in candles]; highs=[c.high for c in candles]; lows=[c.low for c in candles]; vols=[c.volume for c in candles]
        out={}
        for item in self.config.get("indicators", []):
            name=item["name"]; kind=item["type"].upper(); p=item.get("params", {})
            if kind=="SMA": out[name]=sma(closes,p.get("length",20))
            elif kind=="EMA": out[name]=ema(closes,p.get("length",20))
            elif kind=="RSI": out[name]=rsi(closes,p.get("length",14))
            elif kind=="ATR": out[name]=atr(highs,lows,closes,p.get("length",14))
            elif kind=="VWAP": out[name]=vwap(highs,lows,closes,vols)
            elif kind=="MACD": out[name]=macd(closes,p.get("fast",12),p.get("slow",26),p.get("signal",9))
        return out

    def evaluate_completed_candle(self, candles):
        if self.config.get("requires_confirmation", False):
            return None
        vals=self.indicators(candles)
        for rule in self.config.get("entry_rules", []):
            if evaluate(rule, vals):
                return {"action":"BUY","underlying":self.config["underlying"],"reason":rule.get("reason","Configured entry rule matched")}
        return None

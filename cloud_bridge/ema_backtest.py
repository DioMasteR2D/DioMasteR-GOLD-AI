"""EMA crossover backtest with spread/slippage and chronological IS/OOS split."""
from dataclasses import dataclass, asdict
import pandas as pd
from ema_strategy import StrategyConfig, indicators

@dataclass
class BacktestResult:
    trades: int
    wins: int
    losses: int
    net_pnl: float
    win_rate: float
    max_drawdown: float
    split: str

def run_backtest(frame: pd.DataFrame, config: StrategyConfig = StrategyConfig(),
                 spread: float = 0.0, slippage: float = 0.0,
                 split: str = "in_sample") -> dict:
    if spread < 0 or slippage < 0:
        raise ValueError("spread and slippage must be non-negative")
    if not {"timestamp","open","high","low","close"}.issubset(frame.columns):
        raise ValueError("backtest requires timestamp and OHLC columns")
    df = indicators(frame.sort_values("timestamp").reset_index(drop=True), config)
    position = None
    trades, equity, peak, max_dd = [], 0.0, 0.0, 0.0
    for i in range(1, len(df)):
        prev, cur = df.iloc[i-1], df.iloc[i]
        if pd.isna(cur["ema_trend"]) or pd.isna(cur["adx"]) or pd.isna(cur["atr"]):
            continue
        close = float(cur["close"])
        # Stops/targets are evaluated intrabar using candle extremes; stop wins if both touch.
        if position:
            exit_price = None
            if position["side"] == "BUY":
                if float(cur["low"]) <= position["sl"]: exit_price = position["sl"] - slippage
                elif float(cur["high"]) >= position["tp"]: exit_price = position["tp"] - slippage
                elif float(cur["ema_fast"]) < float(cur["ema_slow"]) and close < float(cur["ema_trend"]):
                    exit_price = close - spread/2 - slippage
            else:
                if float(cur["high"]) >= position["sl"]: exit_price = position["sl"] + slippage
                elif float(cur["low"]) <= position["tp"]: exit_price = position["tp"] + slippage
                elif float(cur["ema_fast"]) > float(cur["ema_slow"]) and close > float(cur["ema_trend"]):
                    exit_price = close + spread/2 + slippage
            if exit_price is not None:
                pnl = (exit_price-position["entry"]) if position["side"]=="BUY" else (position["entry"]-exit_price)
                equity += pnl
                trades.append(pnl); peak=max(peak,equity); max_dd=max(max_dd,peak-equity)
                position=None
        cross_up = float(prev["ema_fast"]) <= float(prev["ema_slow"]) and float(cur["ema_fast"]) > float(cur["ema_slow"])
        cross_dn = float(prev["ema_fast"]) >= float(prev["ema_slow"]) and float(cur["ema_fast"]) < float(cur["ema_slow"])
        if position is None and float(cur["adx"]) > config.adx_min:
            side = "BUY" if cross_up and close > float(cur["ema_trend"]) else "SELL" if cross_dn and close < float(cur["ema_trend"]) else None
            if side:
                entry = close + spread/2 + slippage if side=="BUY" else close - spread/2 - slippage
                atr=float(cur["atr"])
                position={"side":side,"entry":entry,
                          "sl":close-config.sl_atr*atr if side=="BUY" else close+config.sl_atr*atr,
                          "tp":close+config.tp_atr*atr if side=="BUY" else close-config.tp_atr*atr}
    # Close any remaining trade at final close, including costs.
    if position and len(df):
        last=float(df.iloc[-1]["close"])
        exit_price=last-spread/2-slippage if position["side"]=="BUY" else last+spread/2+slippage
        pnl=(exit_price-position["entry"]) if position["side"]=="BUY" else (position["entry"]-exit_price)
        equity+=pnl; trades.append(pnl); peak=max(peak,equity); max_dd=max(max_dd,peak-equity)
    wins=sum(x>0 for x in trades); losses=sum(x<=0 for x in trades)
    return asdict(BacktestResult(len(trades),wins,losses,equity,
        wins/len(trades) if trades else 0.0,max_dd,split))

def run_split_backtest(frame: pd.DataFrame, split_timestamp: float, **kwargs) -> dict:
    ordered=frame.sort_values("timestamp")
    ins=ordered[ordered["timestamp"].astype(float)<float(split_timestamp)]
    oos=ordered[ordered["timestamp"].astype(float)>=float(split_timestamp)]
    if len(ins)<10 or len(oos)<10:
        raise ValueError("both in-sample and out-of-sample periods need at least 10 candles")
    return {"in_sample":run_backtest(ins,split="in_sample",**kwargs),
            "out_of_sample":run_backtest(oos,split="out_of_sample",**kwargs)}

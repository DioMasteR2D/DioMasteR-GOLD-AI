"""EMA crossover backtest with spread/slippage and chronological IS/OOS split."""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
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
                 split: str = "in_sample", start_timestamp: float | None = None,
                 news_windows_utc: tuple[str, ...] = ()) -> dict:
    if spread < 0 or slippage < 0:
        raise ValueError("spread and slippage must be non-negative")
    if not {"timestamp","open","high","low","close"}.issubset(frame.columns):
        raise ValueError("backtest requires timestamp and OHLC columns")
    df = indicators(frame.sort_values("timestamp").reset_index(drop=True), config)
    position = None
    trades, equity, peak, max_dd = [], 0.0, 0.0, 0.0
    def is_news_blocked(ts):
        if not news_windows_utc: return False
        dt=datetime.fromtimestamp(float(ts),timezone.utc)
        minute=dt.strftime("%H:%M")
        try:
            for item in news_windows_utc:
                a,b=[v.strip() for v in item.split("-",1)]
                if a<=b and a<=minute<=b: return True
                if a>b and (minute>=a or minute<=b): return True
        except Exception:
            return True
        return False
    for i in range(1, len(df)):
        prev, cur = df.iloc[i-1], df.iloc[i]
        stamp=float(cur["timestamp"])
        if start_timestamp is not None and stamp < float(start_timestamp):
            continue
        if pd.isna(cur["ema_trend"]) or pd.isna(cur["adx"]) or pd.isna(cur["atr"]):
            continue
        close = float(cur["close"])
        # Broker-side SL/TP: if both levels are touched in one OHLC candle,
        # conservatively assume the stop was hit first.
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
                equity += pnl; trades.append(pnl); peak=max(peak,equity); max_dd=max(max_dd,peak-equity)
                position=None
        cross_up = float(prev["ema_fast"]) <= float(prev["ema_slow"]) and float(cur["ema_fast"]) > float(cur["ema_slow"])
        cross_dn = float(prev["ema_fast"]) >= float(prev["ema_slow"]) and float(cur["ema_fast"]) < float(cur["ema_slow"])
        ts_dt=datetime.fromtimestamp(stamp,timezone.utc)
        weekday_block=ts_dt.weekday()>=5
        if position is None and not weekday_block and not is_news_blocked(stamp) and spread<=config.max_spread and float(cur["adx"]) > config.adx_min:
            side = "BUY" if cross_up and close > float(cur["ema_trend"]) else "SELL" if cross_dn and close < float(cur["ema_trend"]) else None
            if side:
                entry = close + spread/2 + slippage if side=="BUY" else close - spread/2 - slippage
                atr=float(cur["atr"])
                position={"side":side,"entry":entry,
                          "sl":close-config.sl_atr*atr if side=="BUY" else close+config.sl_atr*atr,
                          "tp":close+config.tp_atr*atr if side=="BUY" else close-config.tp_atr*atr}
    if position and len(df):
        last=float(df.iloc[-1]["close"])
        exit_price=last-spread/2-slippage if position["side"]=="BUY" else last+spread/2+slippage
        pnl=(exit_price-position["entry"]) if position["side"]=="BUY" else (position["entry"]-exit_price)
        equity+=pnl; trades.append(pnl); peak=max(peak,equity); max_dd=max(max_dd,peak-equity)
    wins=sum(x>0 for x in trades); losses=sum(x<=0 for x in trades)
    return asdict(BacktestResult(len(trades),wins,losses,equity,
        wins/len(trades) if trades else 0.0,max_dd,split))

def run_split_backtest(frame: pd.DataFrame, split_timestamp: float, **kwargs) -> dict:
    ordered=frame.sort_values("timestamp").reset_index(drop=True)
    split=float(split_timestamp)
    ins=ordered[ordered["timestamp"].astype(float)<split]
    # Retain EMA/ADX/ATR warm-up candles before the OOS boundary, but do not
    # allow any trades before split_timestamp in the OOS simulation.
    warmup=max(205,StrategyConfig().trend_ema+5)
    split_idx=int((ordered["timestamp"].astype(float)<split).sum())
    oos=ordered.iloc[max(0,split_idx-warmup):]
    if len(ins)<10 or len(oos[oos["timestamp"].astype(float)>=split])<10:
        raise ValueError("both in-sample and out-of-sample periods need at least 10 candles")
    return {"in_sample":run_backtest(ins,split="in_sample",**kwargs),
            "out_of_sample":run_backtest(oos,split="out_of_sample",start_timestamp=split,**kwargs)}

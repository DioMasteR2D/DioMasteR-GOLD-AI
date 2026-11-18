"""Deterministic EMA 20/50/200 + ADX/ATR backtest for broker OHLC candles.

Input timestamps are UTC epoch seconds and rows must be chronological. Entries are
filled at the next candle open with half-spread + slippage; exits are checked
against candle high/low with conservative stop-first handling when both levels
are touched in one bar. No broker/API access and no order placement.
"""
from dataclasses import asdict, dataclass
from typing import Any
import pandas as pd
from ema_strategy import StrategyConfig, indicators, get_signal

@dataclass
class BacktestConfig:
    spread: float = 0.20
    slippage: float = 0.05
    train_fraction: float = 0.70
    initial_equity: float = 10000.0
    risk_fraction: float = 0.0025

@dataclass
class Trade:
    side: str
    entry_time: float
    exit_time: float
    entry: float
    exit: float
    stop_loss: float
    take_profit: float
    pnl_per_unit: float
    exit_reason: str

def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    required={"timestamp","open","high","low","close"}
    if not isinstance(frame,pd.DataFrame) or not required.issubset(frame.columns):
        raise ValueError("OHLC frame requires timestamp, open, high, low, close")
    df=frame.copy().sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    if len(df)<205: raise ValueError("at least 205 candles required")
    for col in required: df[col]=pd.to_numeric(df[col],errors="raise").astype(float)
    if not df[list(required)].notna().all().all(): raise ValueError("OHLC contains null values")
    if (df.high<df.low).any() or (df.open<df.low).any() or (df.open>df.high).any() or (df.close<df.low).any() or (df.close>df.high).any():
        raise ValueError("invalid OHLC range")
    return df

def run_backtest(frame: pd.DataFrame, strategy: StrategyConfig=StrategyConfig(),
                 config: BacktestConfig=BacktestConfig()) -> dict[str,Any]:
    if config.spread<0 or config.slippage<0 or not 0<config.train_fraction<1:
        raise ValueError("invalid backtest costs or train_fraction")
    df=_prepare(frame)
    split=max(205,min(len(df)-1,int(len(df)*config.train_fraction)))
    partitions={"in_sample":df.iloc[:split].copy(),"out_of_sample":df.iloc[split:].copy()}
    results={}
    for name,part in partitions.items():
        # Indicators are calculated on this partition only: OOS never borrows
        # future data and each partition reports its own independently warmed run.
        if len(part)<205:
            results[name]={"trades":[],"trade_count":0,"net_pnl":0.0,"return_pct":0.0,"win_rate_pct":0.0,"note":"insufficient_partition_for_ema200"}
            continue
        ind=indicators(part,strategy)
        trades=[]
        position=None
        equity=float(config.initial_equity)
        for i in range(1,len(ind)-1):
            bar=ind.iloc[i]
            # Manage an existing position before considering a new signal.
            if position:
                hit_sl=(bar.low<=position["sl"]) if position["side"]=="BUY" else (bar.high>=position["sl"])
                hit_tp=(bar.high>=position["tp"]) if position["side"]=="BUY" else (bar.low<=position["tp"])
                if hit_sl or hit_tp:
                    # If both touched in one OHLC candle, assume the adverse SL first.
                    raw=position["sl"] if hit_sl else position["tp"]
                    fill=raw-config.slippage if position["side"]=="BUY" else raw+config.slippage
                    pnl=(fill-position["entry"]) if position["side"]=="BUY" else (position["entry"]-fill)
                    trades.append(Trade(position["side"],position["time"],float(bar.timestamp),position["entry"],fill,position["sl"],position["tp"],pnl,"SL" if hit_sl else "TP"))
                    equity+=pnl
                    position=None
                    continue
            # Signal on candle i close; execute no earlier than next candle open.
            prefix=part.iloc[:i+1]
            signal=get_signal(prefix,strategy,spread=config.spread)
            if position and signal.direction in ("BUY","SELL") and signal.direction!=position["side"]:
                nxt=ind.iloc[i+1]
                raw=float(nxt.open)
                fill=raw-config.spread/2-config.slippage if position["side"]=="BUY" else raw+config.spread/2+config.slippage
                pnl=(fill-position["entry"]) if position["side"]=="BUY" else (position["entry"]-fill)
                trades.append(Trade(position["side"],position["time"],float(nxt.timestamp),position["entry"],fill,position["sl"],position["tp"],pnl,"OPPOSITE_SIGNAL"))
                equity+=pnl
                position=None
            if position is None and signal.direction in ("BUY","SELL"):
                nxt=ind.iloc[i+1]
                if pd.Timestamp(float(bar.timestamp),unit="s",tz="UTC").weekday()>=5: continue
                raw=float(nxt.open)
                entry=raw+config.spread/2+config.slippage if signal.direction=="BUY" else raw-config.spread/2-config.slippage
                # Re-anchor the ATR distances to the actual next-open fill.
                dist=abs(signal.close-signal.stop_loss)
                reward=abs(signal.take_profit-signal.close)
                sl=entry-dist if signal.direction=="BUY" else entry+dist
                tp=entry+reward if signal.direction=="BUY" else entry-reward
                position={"side":signal.direction,"entry":entry,"sl":sl,"tp":tp,"time":float(nxt.timestamp)}
        results[name]={"trades":[asdict(t) for t in trades],"trade_count":len(trades),
          "net_pnl":round(sum(t.pnl_per_unit for t in trades),6),
          "return_pct":round((sum(t.pnl_per_unit for t in trades)/config.initial_equity)*100,6),
          "win_rate_pct":round((sum(t.pnl_per_unit>0 for t in trades)/len(trades))*100,4) if trades else 0.0,
          "open_position_at_end":bool(position)}
    return {"strategy":{"timeframe":strategy.timeframe,"fast_ema":strategy.fast_ema,"slow_ema":strategy.slow_ema,"trend_ema":strategy.trend_ema,"adx_period":strategy.adx_period,"adx_min":strategy.adx_min,"atr_period":strategy.atr_period,"sl_atr":strategy.sl_atr,"tp_atr":strategy.tp_atr},
      "costs":asdict(config),"split_index":split,"in_sample":results["in_sample"],"out_of_sample":results["out_of_sample"]}

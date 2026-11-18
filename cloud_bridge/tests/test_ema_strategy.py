import numpy as np
import pandas as pd
import pytest
from ema_strategy import StrategyConfig, indicators, get_signal
from backtest import BacktestConfig, run_backtest

def candles(n=520):
    x=np.arange(n,dtype=float)
    close=2300+0.08*x+2*np.sin(x/7)
    return pd.DataFrame({"timestamp":1700000000+x*900,"open":close-0.2,
      "high":close+1.2,"low":close-1.2,"close":close,"spread":0.2})

def test_strategy_defaults_match_requested_spec():
    c=StrategyConfig()
    assert (c.timeframe,c.fast_ema,c.slow_ema,c.trend_ema)==("M5",20,50,200)
    assert (c.adx_period,c.adx_min,c.atr_period)==(14,20,14)
    assert (c.sl_atr,c.tp_atr)==(1.5,3.0)

def test_indicators_produce_expected_columns_and_finite_tail():
    out=indicators(candles())
    for col in ("ema_fast","ema_slow","ema_trend","adx","atr"):
        assert col in out
        assert np.isfinite(out[col].iloc[-1])

def test_signal_fails_closed_on_missing_timestamp():
    frame=candles().drop(columns=["timestamp"])
    assert get_signal(frame).direction=="HOLD"

def test_signal_only_has_allowed_directions_and_closed_bar_stamp():
    frame=candles()
    signal=get_signal(frame,spread=0.1)
    assert signal.direction in ("BUY","SELL","HOLD")
    assert signal.candle_time==float(frame.timestamp.iloc[-1])

def test_spread_filter_blocks_entry():
    frame=candles()
    c=StrategyConfig(max_spread=0.1)
    sig=get_signal(frame,c,spread=0.5)
    assert sig.direction=="HOLD"
    assert sig.reason=="spread_filter"

def test_backtest_returns_separate_train_and_test_windows():
    result=run_backtest(candles(),config=BacktestConfig(spread=0.2,slippage=0.05,train_fraction=0.7))
    assert "in_sample" in result and "out_of_sample" in result
    assert result["split_index"]==int(520*0.7)
    assert "trade_count" in result["in_sample"]
    assert "trade_count" in result["out_of_sample"]

def test_backtest_rejects_negative_execution_costs():
    with pytest.raises(ValueError):
        run_backtest(candles(),config=BacktestConfig(spread=-0.1))

def test_backtest_rejects_invalid_ohlc():
    frame=candles()
    frame.loc[0,"high"]=frame.loc[0,"low"]-1
    with pytest.raises(ValueError):
        run_backtest(frame)

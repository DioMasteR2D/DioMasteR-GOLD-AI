import sys, unittest
from pathlib import Path
import numpy as np
import pandas as pd
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ema_strategy import StrategyConfig, indicators, get_signal

class EmaStrategyTests(unittest.TestCase):
    def candles(self, n=260):
        x=np.arange(n,dtype=float)
        close=2000+0.02*x+0.3*np.sin(x/5)
        return pd.DataFrame({"timestamp":1700000000+x*900,"open":close-0.1,
          "high":close+0.8+0.1*np.sin(x),"low":close-0.8,"close":close})
    def config(self):
        return StrategyConfig(fast_ema=5,slow_ema=10,trend_ema=20,adx_period=5,
          adx_min=0,atr_period=5,sl_atr=1.5,tp_atr=3,max_spread=1.0)
    def test_indicators_exist_and_are_finite_after_warmup(self):
        out=indicators(self.candles(),self.config())
        for col in ("ema_fast","ema_slow","ema_trend","adx","atr"):
            self.assertTrue(np.isfinite(out[col].dropna()).all())
    def test_signal_uses_completed_candle_timestamp(self):
        df=self.candles()
        signal=get_signal(df,self.config(),spread=0.1)
        self.assertEqual(signal.candle_time,float(df.timestamp.iloc[-1]))
        self.assertIn(signal.direction,("BUY","SELL","HOLD"))
    def test_recent_closed_crossover_is_not_missed(self):
        cfg=self.config()
        frame=self.candles(30)
        fake=frame.copy()
        fake["ema_fast"]=np.array([9.0]*27+[9.0,11.0,12.0])
        fake["ema_slow"]=10.0
        fake["ema_trend"]=8.0
        fake["adx"]=30.0
        fake["atr"]=1.0
        fake.loc[29,"close"]=12.0
        with patch("ema_strategy.indicators", return_value=fake):
            signal=get_signal(frame,cfg,spread=0.1)
        self.assertEqual(signal.direction,"BUY")
        self.assertEqual(signal.reason,"ema_crossover_confirmed_on_close")

    def test_bearish_trend_pullback_can_trigger_sell(self):
        cfg=self.config()
        frame=self.candles(30)
        fake=frame.copy()
        fake["ema_fast"]=10.0
        fake["ema_slow"]=11.0
        fake["ema_trend"]=12.0
        fake["adx"]=30.0
        fake["atr"]=1.0
        fake["close"]=np.array([9.0]*28+[10.5,9.0])
        fake.loc[28,"close"]=10.5
        fake.loc[29,"close"]=9.0
        with patch("ema_strategy.indicators", return_value=fake):
            signal=get_signal(frame,cfg,spread=0.1)
        self.assertEqual(signal.direction,"SELL")
        self.assertEqual(signal.reason,"ema_trend_pullback_confirmed_on_close")

    def test_bullish_trend_pullback_can_trigger_buy(self):
        cfg=self.config()
        frame=self.candles(30)
        fake=frame.copy()
        fake["ema_fast"]=11.0
        fake["ema_slow"]=10.0
        fake["ema_trend"]=9.0
        fake["adx"]=30.0
        fake["atr"]=1.0
        fake["close"]=np.array([12.0]*28+[10.5,12.0])
        fake.loc[28,"close"]=10.5
        fake.loc[29,"close"]=12.0
        with patch("ema_strategy.indicators", return_value=fake):
            signal=get_signal(frame,cfg,spread=0.1)
        self.assertEqual(signal.direction,"BUY")
        self.assertEqual(signal.reason,"ema_trend_pullback_confirmed_on_close")

    def test_bearish_ema20_wick_rejection_can_trigger_sell(self):
        cfg=self.config()
        frame=self.candles(30)
        fake=frame.copy()
        fake["ema_fast"]=10.0
        fake["ema_slow"]=11.0
        fake["ema_trend"]=12.0
        fake["adx"]=30.0
        fake["atr"]=1.0
        fake["close"]=9.0
        fake["high"]=9.5
        fake.loc[29,"high"]=10.2
        with patch("ema_strategy.indicators", return_value=fake):
            signal=get_signal(frame,cfg,spread=0.1)
        self.assertEqual(signal.direction,"SELL")
        self.assertEqual(signal.reason,"ema_trend_pullback_confirmed_on_close")

    def test_bullish_ema20_wick_rejection_can_trigger_buy(self):
        cfg=self.config()
        frame=self.candles(30)
        fake=frame.copy()
        fake["ema_fast"]=11.0
        fake["ema_slow"]=10.0
        fake["ema_trend"]=9.0
        fake["adx"]=30.0
        fake["atr"]=1.0
        fake["close"]=12.0
        fake["low"]=11.5
        fake.loc[29,"low"]=10.8
        with patch("ema_strategy.indicators", return_value=fake):
            signal=get_signal(frame,cfg,spread=0.1)
        self.assertEqual(signal.direction,"BUY")
        self.assertEqual(signal.reason,"ema_trend_pullback_confirmed_on_close")


    def test_bearish_ema50_deep_pullback_can_trigger_sell(self):
        cfg=self.config()
        frame=self.candles(30)
        fake=frame.copy()
        fake["ema_fast"]=10.0
        fake["ema_slow"]=11.0
        fake["ema_trend"]=12.0
        fake["adx"]=30.0
        fake["atr"]=1.0
        fake["open"]=11.0
        fake["close"]=9.0
        fake["high"]=9.5
        fake.loc[29,"high"]=11.2
        with patch("ema_strategy.indicators", return_value=fake):
            signal=get_signal(frame,cfg,spread=0.1)
        self.assertEqual(signal.direction,"SELL")
        self.assertEqual(signal.reason,"ema50_deep_pullback_confirmed_on_close")

    def test_bullish_ema50_deep_pullback_can_trigger_buy(self):
        cfg=self.config()
        frame=self.candles(30)
        fake=frame.copy()
        fake["ema_fast"]=11.0
        fake["ema_slow"]=10.0
        fake["ema_trend"]=9.0
        fake["adx"]=30.0
        fake["atr"]=1.0
        fake["open"]=11.5
        fake["close"]=12.0
        fake["low"]=11.2
        fake.loc[29,"low"]=9.8
        with patch("ema_strategy.indicators", return_value=fake):
            signal=get_signal(frame,cfg,spread=0.1)
        self.assertEqual(signal.direction,"BUY")
        self.assertEqual(signal.reason,"ema50_deep_pullback_confirmed_on_close")

    def test_m5_buy_requires_bullish_m15_confirmation(self):
        cfg=self.config()
        frame=self.candles(30)
        entry=frame.copy()
        entry["ema_fast"]=np.array([9.0]*27+[9.0,11.0,12.0])
        entry["ema_slow"]=10.0
        entry["ema_trend"]=8.0
        entry["adx"]=30.0
        entry["atr"]=1.0
        entry.loc[29,"close"]=12.0
        higher=frame.copy()
        higher["ema_fast"]=11.0
        higher["ema_slow"]=10.0
        higher["ema_trend"]=9.0
        with patch("ema_strategy.indicators", side_effect=[entry,higher]):
            signal=get_signal(frame,cfg,spread=0.1,trend_frame=frame)
        self.assertEqual(signal.direction,"BUY")

    def test_m5_buy_is_blocked_by_bearish_m15_confirmation(self):
        cfg=self.config()
        frame=self.candles(30)
        entry=frame.copy()
        entry["ema_fast"]=np.array([9.0]*27+[9.0,11.0,12.0])
        entry["ema_slow"]=10.0
        entry["ema_trend"]=8.0
        entry["adx"]=30.0
        entry["atr"]=1.0
        entry.loc[29,"close"]=12.0
        higher=frame.copy()
        higher["ema_fast"]=9.0
        higher["ema_slow"]=10.0
        higher["ema_trend"]=12.0
        with patch("ema_strategy.indicators", side_effect=[entry,higher]):
            signal=get_signal(frame,cfg,spread=0.1,trend_frame=frame)
        self.assertEqual(signal.direction,"HOLD")
        self.assertEqual(signal.reason,"m5_signal_conflicts_with_m15_trend")

    def test_m5_continuation_entry_does_not_wait_for_new_crossover(self):
        cfg=self.config()
        frame=self.candles(30)
        entry=frame.copy()
        entry["ema_fast"]=11.0
        entry["ema_slow"]=10.0
        entry["ema_trend"]=9.0
        entry["adx"]=30.0
        entry["atr"]=1.0
        entry["open"]=11.0
        entry["close"]=11.5
        higher=frame.copy()
        higher["ema_fast"]=11.0
        higher["ema_slow"]=10.0
        higher["ema_trend"]=9.0
        with patch("ema_strategy.indicators", side_effect=[entry,higher]):
            signal=get_signal(frame,cfg,spread=0.1,trend_frame=frame)
        self.assertEqual(signal.direction,"BUY")
        self.assertEqual(signal.reason,"m5_trend_continuation_confirmed_on_close")

    def test_m5_continuation_entry_requires_m15_direction(self):
        cfg=self.config()
        frame=self.candles(30)
        entry=frame.copy()
        entry["ema_fast"]=10.0
        entry["ema_slow"]=11.0
        entry["ema_trend"]=12.0
        entry["adx"]=30.0
        entry["atr"]=1.0
        entry["open"]=10.0
        entry["close"]=9.5
        higher=frame.copy()
        higher["ema_fast"]=10.0
        higher["ema_slow"]=11.0
        higher["ema_trend"]=12.0
        with patch("ema_strategy.indicators", side_effect=[entry,higher]):
            signal=get_signal(frame,cfg,spread=0.1,trend_frame=frame)
        self.assertEqual(signal.direction,"SELL")
        self.assertEqual(signal.reason,"m5_trend_continuation_confirmed_on_close")

    def test_old_crossover_is_not_reused(self):
        cfg=self.config()
        frame=self.candles(30)
        fake=frame.copy()
        fake["ema_fast"]=np.array([9.0]+[11.0]*29)
        fake["ema_slow"]=10.0
        fake["ema_trend"]=8.0
        fake["adx"]=30.0
        fake["atr"]=1.0
        with patch("ema_strategy.indicators", return_value=fake):
            signal=get_signal(frame,cfg,spread=0.1)
        self.assertEqual(signal.direction,"HOLD")
        self.assertEqual(signal.reason,"no_crossover_or_trend_pullback_within_3_closed_bars")

    def test_wide_spread_blocks_signal(self):
        signal=get_signal(self.candles(),self.config(),spread=9)
        self.assertEqual(signal.direction,"HOLD")
        self.assertEqual(signal.reason,"spread_filter")
    def test_news_window_blocks_signal(self):
        signal=get_signal(self.candles(),self.config(),news_blocked=True)
        self.assertEqual(signal.reason,"news_window")
    def test_invalid_ohlc_fails_closed(self):
        df=self.candles(); df.loc[0,"high"]=float("nan")
        self.assertEqual(get_signal(df,self.config()).direction,"HOLD")

if __name__=="__main__": unittest.main()

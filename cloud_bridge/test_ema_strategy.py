import sys, unittest
from pathlib import Path
import numpy as np
import pandas as pd
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

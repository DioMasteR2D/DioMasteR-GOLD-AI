import unittest
import pandas as pd
from unittest.mock import patch
from adaptive_strategy import _setup
from adaptive_strategy import get_adaptive_signal, _valid

class AdaptiveStrategyTests(unittest.TestCase):
    def test_rejects_missing_timeframes(self):
        empty=pd.DataFrame(columns=["open","high","low","close"])
        signal=get_adaptive_signal(empty,empty,empty,empty)
        self.assertEqual(signal.direction,"HOLD")
        self.assertIn("Insufficient",signal.details)

    def test_requires_real_ohlc_columns(self):
        frame=pd.DataFrame({"close":[1.0]*100})
        self.assertFalse(_valid(frame,30))

    def test_pullback_touch_four_closed_candles_back_is_recognized(self):
        n=30
        close=pd.Series([102.5]*n)
        high=pd.Series([104.0]*n)
        low=pd.Series([101.0]*n)
        open_=pd.Series([102.0]*n)
        low.iloc[-5]=101.8
        open_.iloc[-1]=102.4
        close.iloc[-1]=103.0
        high.iloc[-1]=103.2
        low.iloc[-1]=102.3
        ema20=pd.Series([100.0]*n)
        ema50=pd.Series([102.0]*n)
        rsi=pd.Series([55.0]*n)
        atr=pd.Series([1.0]*n)
        frame=pd.DataFrame({'open':open_,'high':high,'low':low,'close':close})
        with patch('adaptive_strategy._ind', return_value=(close,high,low,ema20,ema50,rsi,atr)):
            result=_setup(frame,'BUY')
        self.assertIsNotNone(result)
        self.assertEqual(result[0],'EMA_PULLBACK')

    def test_never_returns_trade_without_required_candle_history(self):
        rows=[]
        for i in range(100):
            p=2000+i*0.1
            rows.append({"open":p,"high":p+0.2,"low":p-0.2,"close":p+0.05,"tick_volume":100})
        short=pd.DataFrame(rows[:20])
        full=pd.DataFrame(rows)
        signal=get_adaptive_signal(full,full,short,short)
        self.assertEqual(signal.direction,"HOLD")

if __name__ == "__main__":
    unittest.main()

import unittest
import pandas as pd
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

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adaptive_strategy import get_adaptive_signal, _valid

def frame(values):
    values=np.asarray(values,dtype=float)
    return pd.DataFrame({
        "open":values-0.05,
        "high":values+0.20,
        "low":values-0.20,
        "close":values,
    })

class SniperStrategyTests(unittest.TestCase):
    def test_requires_real_ohlc_and_minimum_history(self):
        self.assertFalse(_valid(pd.DataFrame({"close":[1.0]*50}),25))
        empty=pd.DataFrame(columns=["open","high","low","close"])
        self.assertEqual(get_adaptive_signal(None,None,empty,empty).direction,"HOLD")

    def test_flat_market_does_not_force_an_entry(self):
        data=frame(np.full(80,2000.0))
        signal=get_adaptive_signal(None,None,data,data)
        self.assertEqual(signal.direction,"HOLD")
        self.assertFalse(signal.news_block)

    def test_signal_contract_and_quick_target_risk_ratio(self):
        values=np.linspace(2000,2002,80)
        data=frame(values)
        signal=get_adaptive_signal(None,None,data,data)
        self.assertIn(signal.direction,("HOLD","BUY","SELL"))
        self.assertFalse(signal.news_block)
        if signal.direction in ("BUY","SELL"):
            risk=abs(signal.entry-signal.stop_loss)
            reward=abs(signal.take_profit-signal.entry)
            self.assertGreater(risk,0)
            self.assertAlmostEqual(reward/risk,1.25,places=5)

if __name__=="__main__":
    unittest.main()

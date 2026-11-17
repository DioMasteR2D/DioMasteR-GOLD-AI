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

    def test_recent_m5_breakout_retest_and_m1_rejection_produces_buy(self):
        m5=frame(np.full(80,2000.0))
        m5["open"]=1999.95
        m5["high"]=2000.10
        m5["low"]=1999.90
        m5["close"]=2000.00
        m5.loc[76,["open","high","low","close"]]=[2000.12,2000.40,2000.12,2000.35]
        m5.loc[78,["open","high","low","close"]]=[2000.11,2000.20,2000.08,2000.14]
        m5.loc[79,["open","high","low","close"]]=[2000.14,2000.25,2000.12,2000.20]
        m1=frame(np.full(30,2000.0))
        m1.loc[28,["open","high","low","close"]]=[2000.10,2000.16,2000.08,2000.12]
        m1.loc[29,["open","high","low","close"]]=[2000.12,2000.22,2000.08,2000.18]
        signal=get_adaptive_signal(None,None,m5,m1)
        self.assertEqual(signal.direction,"BUY",signal.details)
        self.assertEqual(signal.setup,"SNIPER_BREAKOUT_RETEST")
        self.assertAlmostEqual(abs(signal.take_profit-signal.entry)/abs(signal.entry-signal.stop_loss),1.25,places=5)

    def test_confirmed_sell_breakout_retest_produces_sell(self):
        m5=frame(np.full(80,2000.0))
        m5["open"]=2000.05
        m5["high"]=2000.10
        m5["low"]=1999.90
        m5["close"]=2000.00
        m5.loc[76,["open","high","low","close"]]=[1999.88,1999.88,1999.60,1999.65]
        m5.loc[78,["open","high","low","close"]]=[1999.89,1999.92,1999.80,1999.86]
        m5.loc[79,["open","high","low","close"]]=[1999.86,1999.88,1999.75,1999.80]
        m1=frame(np.full(30,2000.0))
        m1.loc[28,["open","high","low","close"]]=[1999.90,1999.94,1999.84,1999.88]
        m1.loc[29,["open","high","low","close"]]=[1999.88,1999.92,1999.78,1999.82]
        signal=get_adaptive_signal(None,None,m5,m1)
        self.assertEqual(signal.direction,"SELL",signal.details)
        self.assertEqual(signal.setup,"SNIPER_BREAKOUT_RETEST")

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

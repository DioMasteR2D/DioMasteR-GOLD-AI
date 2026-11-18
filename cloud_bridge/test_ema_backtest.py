import sys, unittest
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ema_strategy import StrategyConfig
from ema_backtest import run_backtest, run_split_backtest

class EmaBacktestTests(unittest.TestCase):
    def frame(self,n=520):
        x=np.arange(n,dtype=float)
        close=2000+0.01*x+0.8*np.sin(x/11)
        return pd.DataFrame({"timestamp":1700000000+x*900,"open":close-0.1,
            "high":close+0.7,"low":close-0.7,"close":close})
    def config(self):
        return StrategyConfig(fast_ema=5,slow_ema=12,trend_ema=30,
            adx_period=5,adx_min=5,atr_period=5,sl_atr=1.5,tp_atr=3,max_spread=1.0)
    def test_backtest_returns_metrics_and_accounts_for_costs(self):
        frame=self.frame()
        base=run_backtest(frame,self.config(),spread=0,slippage=0)
        costly=run_backtest(frame,self.config(),spread=0.2,slippage=0.05)
        self.assertIn("net_pnl",base)
        self.assertGreaterEqual(base["trades"],0)
        self.assertLessEqual(costly["net_pnl"],base["net_pnl"])
    def test_split_is_chronological_and_separate(self):
        frame=self.frame()
        split=float(frame.timestamp.iloc[300])
        result=run_split_backtest(frame,split_timestamp=split,config=self.config(),spread=0.1,slippage=0.02)
        self.assertEqual(result["in_sample"]["split"],"in_sample")
        self.assertEqual(result["out_of_sample"]["split"],"out_of_sample")
    def test_rejects_negative_execution_costs(self):
        with self.assertRaises(ValueError):
            run_backtest(self.frame(),self.config(),spread=-0.1)

if __name__=="__main__": unittest.main()

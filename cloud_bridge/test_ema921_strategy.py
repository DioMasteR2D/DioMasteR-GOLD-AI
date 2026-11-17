import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adaptive_strategy import get_adaptive_signal, _valid, _ind

def frame(values):
    values = np.asarray(values, dtype=float)
    return pd.DataFrame({
        "open": values - 0.05,
        "high": values + 0.20,
        "low": values - 0.20,
        "close": values,
    })

class CleanEMA921Tests(unittest.TestCase):
    def test_requires_real_ohlc_and_completed_history(self):
        self.assertFalse(_valid(pd.DataFrame({"close": [1.0] * 50}), 25))
        empty = pd.DataFrame(columns=["open", "high", "low", "close"])
        self.assertEqual(get_adaptive_signal(empty, empty, empty, empty).direction, "HOLD")

    def test_indicator_contract_keeps_ema9_ema21_and_atr(self):
        values = np.linspace(2000, 2010, 80)
        close, high, low, ema9, ema21, rsi, atr = _ind(frame(values))
        self.assertEqual(len(ema9), 80)
        self.assertEqual(len(ema21), 80)
        self.assertIsNone(rsi)
        self.assertTrue(np.isfinite(float(atr.iloc[-1])))

    def test_no_legacy_filter_fields_are_required(self):
        values = np.linspace(2000, 2010, 80)
        data = frame(values)
        signal = get_adaptive_signal(data, data, data, data)
        self.assertIn(signal.direction, ("HOLD", "BUY", "SELL"))
        self.assertFalse(signal.news_block)

if __name__ == "__main__":
    unittest.main()

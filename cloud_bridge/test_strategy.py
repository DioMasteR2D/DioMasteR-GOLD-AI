import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import unified_engine
import fundamental_engine
import smc_engine

class StrategyPortTests(unittest.TestCase):
    def test_unified_threshold_is_eight(self):
        self.assertEqual(unified_engine.MIN_UNIFIED_SCORE, 8)

    def test_phase_one_score_caps_at_three(self):
        self.assertEqual(unified_engine.score_phase1(True, True, True), 3)
        self.assertEqual(unified_engine.score_phase1(False, True, False), 1)

    def test_fundamental_failure_fails_closed(self):
        original = fundamental_engine.get_fundamental_signal
        try:
            def unavailable():
                raise RuntimeError("test: FRED/calendar unavailable")
            fundamental_engine.get_fundamental_signal = unavailable
            points, blocked, reason, details = unified_engine.score_phase4("BUY")
            self.assertEqual(points, 0)
            self.assertTrue(blocked)
            self.assertIn("blocked", reason.lower())
        finally:
            fundamental_engine.get_fundamental_signal = original

    def test_smc_engine_exposes_all_four_detectors(self):
        self.assertTrue(callable(smc_engine.detect_order_blocks))
        self.assertTrue(callable(smc_engine.detect_fvg))
        self.assertTrue(callable(smc_engine.detect_bos_choch))
        self.assertTrue(callable(smc_engine.get_smc_signal))

if __name__ == "__main__":
    unittest.main()

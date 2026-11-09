import unittest

import main


def bar(timestamp, price):
    return {
        "timestamp": float(timestamp),
        "open": float(price),
        "high": float(price + 2),
        "low": float(price - 2),
        "close": float(price + 1),
        "tick_volume": 3.0,
        "spread": 0.2,
    }


class AggregateLiveM1CandlesTests(unittest.TestCase):
    def setUp(self):
        main.LIVE_M1_BARS.clear()
        main.LIVE_M1_CURRENT.clear()

    def tearDown(self):
        main.LIVE_M1_BARS.clear()
        main.LIVE_M1_CURRENT.clear()

    def test_aggregates_two_complete_m5_bars_with_ohlc(self):
        start = 1_800_000_000
        start = (start // 300) * 300
        main.LIVE_M1_BARS["XAUUSD"] = [
            bar(start + minute * 60, 100 + minute)
            for minute in range(10)
        ]
        result = main.aggregate_live_m1_candles("XAUUSD", "M5")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["timestamp"], float(start))
        self.assertEqual(result[0]["open"], 100.0)
        self.assertEqual(result[0]["close"], 105.0)
        self.assertEqual(result[0]["high"], 106.0)
        self.assertEqual(result[0]["low"], 98.0)
        self.assertEqual(result[0]["tick_volume"], 15.0)

    def test_rejects_bucket_with_missing_minute_but_keeps_next_complete_bucket(self):
        start = (1_800_000_000 // 300) * 300
        rows = [bar(start + minute * 60, 100 + minute) for minute in range(10)]
        del rows[2]
        main.LIVE_M1_BARS["XAUUSD"] = rows
        result = main.aggregate_live_m1_candles("XAUUSD", "M5")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["timestamp"], float(start + 300))

    def test_excludes_still_forming_current_m1_bar(self):
        start = (1_800_000_000 // 300) * 300
        main.LIVE_M1_BARS["XAUUSD"] = [
            bar(start + minute * 60, 100 + minute) for minute in range(4)
        ]
        main.LIVE_M1_CURRENT["XAUUSD"] = bar(start + 240, 104)
        self.assertEqual(main.aggregate_live_m1_candles("XAUUSD", "M5"), [])

    def test_does_not_aggregate_unsupported_or_insufficient_timeframes(self):
        start = (1_800_000_000 // 3600) * 3600
        main.LIVE_M1_BARS["XAUUSD"] = [
            bar(start + minute * 60, 100 + minute) for minute in range(59)
        ]
        self.assertEqual(main.aggregate_live_m1_candles("XAUUSD", "H1"), [])
        self.assertEqual(main.aggregate_live_m1_candles("XAUUSD", "D1"), [])

    def test_m15_requires_three_complete_contiguous_groups(self):
        start = (1_800_000_000 // 900) * 900
        main.LIVE_M1_BARS["XAUUSD"] = [
            bar(start + minute * 60, 100 + minute) for minute in range(30)
        ]
        result = main.aggregate_live_m1_candles("XAUUSD", "M15")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["tick_volume"], 45.0)


if __name__ == "__main__":
    unittest.main()

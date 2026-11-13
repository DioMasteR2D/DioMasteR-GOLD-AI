"""Safety wrapper for the Phase 4 macro/news gate.

Macro indicators are a score modifier, while the verified USD event calendar
is the hard safety gate. If FRED macro feeds are temporarily unavailable but
the economic calendar was successfully verified, treat macro as neutral rather
than blocking every technically valid setup. Calendar outages remain fail-closed.
"""
from unified_engine import score_phase4 as _score_phase4

def score_phase4(direction: str):
    result = _score_phase4(direction)
    if not isinstance(result, tuple) or len(result) != 4:
        return result
    points, news_block, reason, details = result
    if news_block and "Fundamental data incomplete or USD news calendar unavailable" in str(reason):
        try:
            import fundamental_engine
            calendar_verified = bool(fundamental_engine.EVENTS_SOURCE_OK)
        except Exception:
            calendar_verified = False
        if calendar_verified:
            return (
                1,
                False,
                "",
                "Macro feeds temporarily incomplete; verified USD news calendar clear; neutral macro score",
            )
    return result

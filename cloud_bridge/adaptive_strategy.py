"""Sniper Scalping strategy for XAUUSD MT5 DEMO.

Entry: completed M5 range breakout, controlled retest, then M1 rejection,
engulfing, or momentum confirmation. Only completed broker candles are used.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

MIN_ADAPTIVE_SCORE = 70


@dataclass
class AdaptiveSignal:
    direction: str
    total_score: int
    phase1_score: int
    phase2_score: int
    phase4_score: int
    news_block: bool
    news_reason: str
    confidence: str
    details: str
    setup: str = "NONE"
    entry: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    atr: float = 0.0


def _valid(df, minimum=25):
    return isinstance(df, pd.DataFrame) and len(df) >= minimum and all(
        col in df.columns for col in ("open", "high", "low", "close")
    )


def _atr(df):
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev).abs(), (low - prev).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()


def get_adaptive_signal(h1, h4, m5, m1, d1=None, w1=None):
    hold = AdaptiveSignal(
        "HOLD", 0, 0, 0, 0, False, "", "LOW",
        "SNIPER: waiting for completed M5/M1 broker candles"
    )
    if not (_valid(m5, 30) and _valid(m1, 25)):
        hold.details = "HOLD: insufficient completed M5/M1 candles"
        return hold

    m5 = m5.reset_index(drop=True)
    m1 = m1.reset_index(drop=True)
    atr_series = _atr(m5)
    atr = float(atr_series.iloc[-1]) if np.isfinite(atr_series.iloc[-1]) else 0.0
    if atr <= 0:
        hold.details = "HOLD: M5 ATR not ready"
        return hold

    n = len(m5)
    last5 = m5.iloc[-1]
    last_open = float(last5["open"])
    last_close = float(last5["close"])
    candidate = None
    diagnostics = {"breakout": False, "retest": False, "continuation": False}

    # Evaluate the latest 8 completed M5 bars. Each breakout is measured
    # against the 12 bars immediately before it (no look-ahead).
    for breakout_idx in range(max(12, n - 9), n - 2):
        base = m5.iloc[breakout_idx - 12:breakout_idx]
        if len(base) < 10:
            continue
        local_atr = float(atr_series.iloc[breakout_idx])
        if not np.isfinite(local_atr) or local_atr <= 0:
            continue

        resistance = float(base["high"].astype(float).max())
        support = float(base["low"].astype(float).min())
        breakout = m5.iloc[breakout_idx]
        bo_open = float(breakout["open"])
        bo_close = float(breakout["close"])
        bo_high = float(breakout["high"])
        bo_low = float(breakout["low"])
        bo_range = max(bo_high - bo_low, 1e-9)
        body_ratio = abs(bo_close - bo_open) / bo_range

        side = None
        level = None
        if bo_close > resistance + 0.04 * local_atr and bo_close > bo_open and body_ratio >= 0.35:
            side, level = "BUY", resistance
        elif bo_close < support - 0.04 * local_atr and bo_close < bo_open and body_ratio >= 0.35:
            side, level = "SELL", support
        if side is None:
            continue
        diagnostics["breakout"] = True

        # A retest must happen after the breakout and within four M5 bars.
        retest_end = min(n, breakout_idx + 5)
        for retest_idx in range(breakout_idx + 1, retest_end):
            retest = m5.iloc[retest_idx]
            r_open = float(retest["open"])
            r_close = float(retest["close"])
            r_low = float(retest["low"])
            r_high = float(retest["high"])
            if side == "BUY":
                touched = r_low <= level + 0.22 * local_atr and r_low >= level - 0.55 * local_atr
                held = r_close >= level - 0.08 * local_atr
                continuation = last_close > level and last_close > last_open
            else:
                touched = r_high >= level - 0.22 * local_atr and r_high <= level + 0.55 * local_atr
                held = r_close <= level + 0.08 * local_atr
                continuation = last_close < level and last_close < last_open
            if touched and held:
                diagnostics["retest"] = True
                if continuation:
                    diagnostics["continuation"] = True
                    candidate = (side, level, retest_idx)
        # Keep searching for the most recent valid structure.

    if candidate is None:
        if not diagnostics["breakout"]:
            hold.details = "HOLD: M5 range not broken with a decisive completed candle"
        elif not diagnostics["retest"]:
            hold.details = "HOLD: M5 breakout found; waiting for controlled retest"
        else:
            hold.details = "HOLD: M5 retest found; waiting for M5 continuation"
        return hold

    side, level, retest_idx = candidate
    last1 = m1.iloc[-1]
    prev1 = m1.iloc[-2]
    o = float(last1["open"])
    c = float(last1["close"])
    hi = float(last1["high"])
    lo = float(last1["low"])
    prev_o = float(prev1["open"])
    prev_c = float(prev1["close"])
    body = max(abs(c - o), 1e-9)
    candle_range = max(hi - lo, 1e-9)
    lower_wick = min(o, c) - lo
    upper_wick = hi - max(o, c)
    body_ratio = body / candle_range

    if side == "BUY":
        near_level = c >= level - 0.04 * atr
        rejection = c > o and lower_wick >= 0.20 * body
        engulfing = c > o and prev_c < prev_o and o <= prev_c and c >= prev_o
        momentum = c > o and body_ratio >= 0.62 and c >= hi - 0.25 * candle_range
        confirm = near_level and c > prev_c and (rejection or engulfing or momentum)
        entry = c
        recent_low = float(m5.iloc[-4:]["low"].astype(float).min())
        sl = min(recent_low, lo) - 0.10 * atr
        risk = entry - sl
        tp = entry + 1.25 * risk
    else:
        near_level = c <= level + 0.04 * atr
        rejection = c < o and upper_wick >= 0.20 * body
        engulfing = c < o and prev_c > prev_o and o >= prev_c and c <= prev_o
        momentum = c < o and body_ratio >= 0.62 and c <= lo + 0.25 * candle_range
        confirm = near_level and c < prev_c and (rejection or engulfing or momentum)
        entry = c
        recent_high = float(m5.iloc[-4:]["high"].astype(float).max())
        sl = max(recent_high, hi) + 0.10 * atr
        risk = sl - entry
        tp = entry - 1.25 * risk

    if not confirm:
        hold.details = (
            f"HOLD: M5 {side} breakout/retest valid; M1 needs rejection, "
            "engulfing, or strong momentum close"
        )
        return hold
    if risk <= 0 or risk > 1.8 * atr:
        hold.details = "HOLD: Sniper structural stop outside 1.8 ATR safety range"
        return hold

    trigger = "rejection" if (rejection) else ("engulfing" if engulfing else "momentum")
    return AdaptiveSignal(
        side, 88, 1, 1, 0, False, "", "HIGH",
        f"SNIPER: M5 breakout/retest + M1 {trigger}; structural stop; 1.25R target",
        "SNIPER_BREAKOUT_RETEST", entry, sl, tp, atr
    )

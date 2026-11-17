"""Clean EMA9/EMA21 XAUUSD DEMO strategy.

Only EMA9/EMA21 trend alignment, M5 pullback and M1 confirmation are used.
No SMC, liquidity sweep, BOS, RSI, macro/news scoring or legacy entry filters.
All OHLC input must be completed broker candles supplied by the bridge.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

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

def _ind(df):
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    previous = close.shift(1)
    tr = pd.concat(
        [(high-low), (high-previous).abs(), (low-previous).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    return close, ema9, ema21, atr

def get_adaptive_signal(h1, h4, m5, m1, d1=None, w1=None):
    hold = AdaptiveSignal(
        "HOLD", 0, 0, 0, 0, False, "", "LOW",
        "EMA9/EMA21: waiting for completed broker candles"
    )
    if not all((_valid(h1, 30), _valid(h4, 30), _valid(m5, 30), _valid(m1, 25))):
        hold.details = "HOLD: insufficient completed H1/H4/M5/M1 candles"
        return hold

    h1c, h1e9, h1e21, h1atr = _ind(h1)
    h4c, h4e9, h4e21, h4atr = _ind(h4)
    m5c, m5e9, m5e21, m5atr = _ind(m5)
    m1c, m1e9, m1e21, m1atr = _ind(m1)
    ix = -1

    h1_up = float(h1e9.iloc[ix]) > float(h1e21.iloc[ix])
    h1_down = float(h1e9.iloc[ix]) < float(h1e21.iloc[ix])
    h4_up = float(h4e9.iloc[ix]) > float(h4e21.iloc[ix])
    h4_down = float(h4e9.iloc[ix]) < float(h4e21.iloc[ix])

    if h1_up and h4_up:
        side = "BUY"
    elif h1_down and h4_down:
        side = "SELL"
    else:
        hold.details = "HOLD: H1/H4 EMA9-EMA21 trend not aligned"
        return hold

    # M5 setup: trend-aligned EMA9/21 pullback followed by a directional close.
    m5_open = float(m5["open"].iloc[ix])
    m5_close = float(m5c.iloc[ix])
    m5_prev = float(m5c.iloc[-2])
    m5_fast = float(m5e9.iloc[ix])
    m5_slow = float(m5e21.iloc[ix])
    m5_atr = float(m5atr.iloc[ix]) if np.isfinite(m5atr.iloc[ix]) else 0.0
    if m5_atr <= 0:
        hold.details = "HOLD: M5 ATR not ready"
        return hold

    recent = m5.iloc[-4:]
    recent_low = float(recent["low"].astype(float).min())
    recent_high = float(recent["high"].astype(float).max())
    if side == "BUY":
        trend_ok = m5_fast > m5_slow
        pullback = recent_low <= m5_fast + 0.20*m5_atr
        setup_ok = trend_ok and pullback and m5_close > m5_open and m5_close > m5_prev
    else:
        trend_ok = m5_fast < m5_slow
        pullback = recent_high >= m5_fast - 0.20*m5_atr
        setup_ok = trend_ok and pullback and m5_close < m5_open and m5_close < m5_prev
    if not setup_ok:
        hold.details = f"HOLD: waiting for M5 EMA9/EMA21 pullback continuation ({side})"
        return hold

    # M1 confirmation: EMA9/21 aligned and last completed candle closes in direction.
    m1_open = float(m1["open"].iloc[ix])
    m1_close = float(m1c.iloc[ix])
    m1_prev = float(m1c.iloc[-2])
    if side == "BUY":
        confirm = float(m1e9.iloc[ix]) > float(m1e21.iloc[ix]) and m1_close > m1_open and m1_close > m1_prev
    else:
        confirm = float(m1e9.iloc[ix]) < float(m1e21.iloc[ix]) and m1_close < m1_open and m1_close < m1_prev
    if not confirm:
        hold.details = f"HOLD: M5 setup valid; waiting for M1 EMA9/EMA21 confirmation ({side})"
        return hold

    entry = m1_close
    atr = m5_atr
    if side == "BUY":
        structure = recent_low
        sl = min(structure, entry - 1.2*atr) - 0.10*atr
        risk = entry - sl
        tp = entry + 2.0*risk
    else:
        structure = recent_high
        sl = max(structure, entry + 1.2*atr) + 0.10*atr
        risk = sl - entry
        tp = entry - 2.0*risk
    if risk <= 0 or risk > 3.5*atr:
        hold.details = "HOLD: EMA9/EMA21 stop distance outside safety range"
        return hold

    return AdaptiveSignal(
        side, 85, 1, 1, 0, False, "", "HIGH",
        f"EMA9/EMA21 aligned H4+H1; M5 pullback continuation; M1 confirmed; structural SL; TP 2R",
        "EMA921_PULLBACK", entry, sl, tp, atr
    )

"""Sniper Scalping strategy for XAUUSD MT5 DEMO.

Entry: recent M5 range breakout, controlled retest, and M1 rejection/continuation.
Only completed broker candles are accepted. No indicator-stack or legacy filters.
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
    high=df["high"].astype(float)
    low=df["low"].astype(float)
    close=df["close"].astype(float)
    prev=close.shift(1)
    tr=pd.concat([high-low,(high-prev).abs(),(low-prev).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()

def get_adaptive_signal(h1, h4, m5, m1, d1=None, w1=None):
    hold=AdaptiveSignal("HOLD",0,0,0,0,False,"","LOW",
                        "SNIPER: waiting for completed M5/M1 broker candles")
    if not (_valid(m5,30) and _valid(m1,25)):
        hold.details="HOLD: insufficient completed M5/M1 candles"
        return hold

    m5=m5.reset_index(drop=True)
    m1=m1.reset_index(drop=True)
    atr_series=_atr(m5)
    atr=float(atr_series.iloc[-1]) if np.isfinite(atr_series.iloc[-1]) else 0.0
    if atr<=0:
        hold.details="HOLD: M5 ATR not ready"
        return hold

    # Search the last six completed M5 candles for a real range break followed
    # by a retest. The range is frozen before each breakout (no look-ahead).
    n=len(m5)
    last5=m5.iloc[-1]
    last_open=float(last5["open"])
    last_close=float(last5["close"])
    recent=m5.iloc[-3:]
    recent_low=float(recent["low"].astype(float).min())
    recent_high=float(recent["high"].astype(float).max())
    candidate=None
    for breakout_idx in range(max(12,n-7),n-2):
        base=m5.iloc[breakout_idx-12:breakout_idx]
        if len(base)<10:
            continue
        resistance=float(base["high"].astype(float).max())
        support=float(base["low"].astype(float).min())
        breakout=m5.iloc[breakout_idx]
        bo_open=float(breakout["open"])
        bo_close=float(breakout["close"])
        # Ignore marginal pokes: the completed breakout must clear the range.
        if bo_close>resistance+0.03*atr and bo_close>bo_open:
            for retest_idx in range(breakout_idx+1,n):
                retest=m5.iloc[retest_idx]
                retest_low=float(retest["low"])
                retest_high=float(retest["high"])
                # Retest may occur on the last or penultimate closed candle;
                # the latest closed M5 candle must still confirm direction.
                if (retest_low<=resistance+0.18*atr
                    and retest_low>=resistance-0.50*atr
                    and last_close>resistance and last_close>last_open):
                    candidate=("BUY",resistance,retest_idx)
        if bo_close<support-0.03*atr and bo_close<bo_open:
            for retest_idx in range(breakout_idx+1,n):
                retest=m5.iloc[retest_idx]
                retest_low=float(retest["low"])
                retest_high=float(retest["high"])
                if (retest_high>=support-0.18*atr
                    and retest_high<=support+0.50*atr
                    and last_close<support and last_close<last_open):
                    candidate=("SELL",support,retest_idx)
    if candidate is None:
        hold.details="HOLD: no completed M5 breakout + retest + continuation in recent 6 bars"
        return hold

    side,level,retest_idx=candidate
    last1=m1.iloc[-1]
    prev1=m1.iloc[-2]
    o=float(last1["open"]); c=float(last1["close"])
    hi=float(last1["high"]); lo=float(last1["low"])
    body=max(abs(c-o),1e-9)
    lower_wick=min(o,c)-lo
    upper_wick=hi-max(o,c)
    if side=="BUY":
        confirm=(c>o and c>level-0.05*atr and lower_wick>=0.15*body
                 and c>float(prev1["close"]))
        entry=c
        sl=min(recent_low,lo)-0.10*atr
        risk=entry-sl
        tp=entry+1.25*risk
    else:
        confirm=(c<o and c<level+0.05*atr and upper_wick>=0.15*body
                 and c<float(prev1["close"]))
        entry=c
        sl=max(recent_high,hi)+0.10*atr
        risk=sl-entry
        tp=entry-1.25*risk
    if not confirm:
        hold.details=f"HOLD: M5 {side} breakout retest confirmed; waiting for M1 rejection"
        return hold
    if risk<=0 or risk>1.8*atr:
        hold.details="HOLD: Sniper structural stop outside 1.8 ATR safety range"
        return hold
    return AdaptiveSignal(side,85,1,1,0,False,"","HIGH",
        "SNIPER recent M5 breakout + retest + M1 rejection; structural stop; quick 1.25R target",
        "SNIPER_BREAKOUT_RETEST",entry,sl,tp,atr)

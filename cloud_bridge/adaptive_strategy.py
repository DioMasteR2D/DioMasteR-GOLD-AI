"""Sniper Scalping strategy for XAUUSD MT5 DEMO.

Entry: M5 range breakout, controlled retest, and M1 rejection confirmation.
No EMA crossover, RSI, SMC, liquidity, macro/news or legacy scoring filters.
Only completed broker candles are accepted.
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

    # Breakout level is calculated only from candles preceding the current
    # retest window, avoiding look-ahead into the setup candle.
    prior=m5.iloc[-14:-3]
    if len(prior)<10:
        hold.details="HOLD: insufficient M5 range history"
        return hold
    resistance=float(prior["high"].astype(float).max())
    support=float(prior["low"].astype(float).min())
    recent=m5.iloc[-3:]
    recent_low=float(recent["low"].astype(float).min())
    recent_high=float(recent["high"].astype(float).max())
    last5=m5.iloc[-1]
    last5_close=float(last5["close"])
    last5_open=float(last5["open"])

    # A valid retest must revisit the broken level without closing deeply
    # back inside the old range, then finish in breakout direction.
    buy_retest=(float(recent.iloc[-1]["low"])<=resistance+0.12*atr
                and float(recent.iloc[-1]["low"])>=resistance-0.35*atr
                and last5_close>resistance and last5_close>last5_open)
    sell_retest=(float(recent.iloc[-1]["high"])>=support-0.12*atr
                 and float(recent.iloc[-1]["high"])<=support+0.35*atr
                 and last5_close<support and last5_close<last5_open)
    if buy_retest:
        side="BUY"
        level=resistance
    elif sell_retest:
        side="SELL"
        level=support
    else:
        hold.details="HOLD: waiting for M5 breakout retest"
        return hold

    # M1 rejection/continuation confirmation at the retested breakout level.
    last1=m1.iloc[-1]
    prev1=m1.iloc[-2]
    o=float(last1["open"]); c=float(last1["close"])
    hi=float(last1["high"]); lo=float(last1["low"])
    body=max(abs(c-o),1e-9)
    lower_wick=min(o,c)-lo
    upper_wick=hi-max(o,c)
    if side=="BUY":
        confirm=(c>o and c>level and lower_wick>=0.25*body
                 and c>float(prev1["close"]))
        entry=c
        sl=min(recent_low,lo)-0.12*atr
        risk=entry-sl
        tp=entry+1.25*risk
    else:
        confirm=(c<o and c<level and upper_wick>=0.25*body
                 and c<float(prev1["close"]))
        entry=c
        sl=max(recent_high,hi)+0.12*atr
        risk=sl-entry
        tp=entry-1.25*risk
    if not confirm:
        hold.details=f"HOLD: M5 {side} retest found; waiting for M1 rejection"
        return hold
    if risk<=0 or risk>1.8*atr:
        hold.details="HOLD: Sniper structural stop outside 1.8 ATR safety range"
        return hold
    return AdaptiveSignal(side,85,1,1,0,False,"","HIGH",
        "SNIPER breakout + M5 retest + M1 rejection; structural stop; quick 1.25R target",
        "SNIPER_BREAKOUT_RETEST",entry,sl,tp,atr)

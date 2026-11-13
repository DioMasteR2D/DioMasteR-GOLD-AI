"""Adaptive Liquidity Hunter for XAUUSD.

Uses completed broker OHLC only. M5 defines the immediate scalp direction and
identifies liquidity sweep, BOS/retest, EMA pullback or breakout/retest; M1
confirms timing. H1/H4 are intentionally not used as entry filters. The
fundamental/news gate remains a hard safety filter.
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

def _valid(df, minimum):
    return isinstance(df, pd.DataFrame) and len(df) >= minimum and all(
        c in df.columns for c in ("open", "high", "low", "close"))

def _ind(df):
    c=df["close"].astype(float); h=df["high"].astype(float); l=df["low"].astype(float)
    ema20=c.ewm(span=20, adjust=False).mean()
    ema50=c.ewm(span=50, adjust=False).mean()
    delta=c.diff()
    gain=delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss=(-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rsi=100-(100/(1+gain/loss.replace(0,np.nan)))
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    return c,h,l,ema20,ema50,rsi,atr

def _setup(m15, side):
    """Fast M5 entry setup; inspect the latest three CLOSED M5 candles."""
    c,h,l,e20,e50,rsi,atr=_ind(m15)
    last=len(m15)-1
    if last < 25 or not np.isfinite(atr.iloc[last]) or atr.iloc[last] <= 0:
        return None
    # Prefer the newest valid setup, but do not discard a setup merely because
    # the next one or two closed M5 candles are the confirmation/retest candle.
    for i in range(last, max(24,last-3), -1):
        if not np.isfinite(atr.iloc[i]) or float(atr.iloc[i]) <= 0:
            continue
        o=float(m15["open"].iloc[i]); close=float(c.iloc[i]); high=float(h.iloc[i]); low=float(l.iloc[i])
        a=float(atr.iloc[i]); prior_high=float(h.iloc[i-20:i].max()); prior_low=float(l.iloc[i-20:i].min())
        body=max(abs(close-o),a*0.02); lower_wick=min(o,close)-low; upper_wick=high-max(o,close)
        if side=="BUY" and low < prior_low and close > prior_low and lower_wick >= body*0.8:
            return ("LIQUIDITY_SWEEP", 30, low)
        if side=="SELL" and high > prior_high and close < prior_high and upper_wick >= body*0.8:
            return ("LIQUIDITY_SWEEP", 30, high)
        prev_close=float(c.iloc[i-1]); prior_res=float(h.iloc[i-11:i-1].max()); prior_sup=float(l.iloc[i-11:i-1].min())
        if side=="BUY" and prev_close > prior_res and low <= prior_res and close > prior_res and close > o:
            return ("BOS_RETEST", 27, min(low,prior_res))
        if side=="SELL" and prev_close < prior_sup and high >= prior_sup and close < prior_sup and close < o:
            return ("BOS_RETEST", 27, max(high,prior_sup))
        zone_low=min(float(e20.iloc[i]),float(e50.iloc[i])); zone_high=max(float(e20.iloc[i]),float(e50.iloc[i]))
        recent_low=float(l.iloc[max(0,i-4):i+1].min()); recent_high=float(h.iloc[max(0,i-4):i+1].max())
        touch_buffer=0.15*a
        if side=="BUY" and recent_low <= zone_high+touch_buffer and close > float(e20.iloc[i]) and close > o:
            return ("EMA_PULLBACK", 23, min(recent_low, float(e20.iloc[i])))
        if side=="SELL" and recent_high >= zone_low-touch_buffer and close < float(e20.iloc[i]) and close < o:
            return ("EMA_PULLBACK", 23, max(recent_high, float(e20.iloc[i])))
        range_high=float(h.iloc[max(0,i-13):i-1].max()); range_low=float(l.iloc[max(0,i-13):i-1].min())
        if side=="BUY" and prev_close > range_high and low <= range_high and close > range_high:
            return ("BREAKOUT_RETEST", 25, low)
        if side=="SELL" and prev_close < range_low and high >= range_low and close < range_low:
            return ("BREAKOUT_RETEST", 25, high)
    return None

def _m5_confirm(m5, side):
    """Fast M1 timing confirmation: latest closed candle plus recent momentum."""
    if not _valid(m5, 22): return False
    c,h,l,ema20,ema50,rsi,atr=_ind(m5); i=len(m5)-1
    # Use a short 3-candle window so a valid M1 impulse is not lost to one
    # small pause candle. The latest candle must still close in trade direction.
    recent=m5.iloc[i-2:i+1]
    o=float(m5["open"].iloc[i]); close=float(c.iloc[i]); prev=float(c.iloc[i-1])
    directional=close>o if side=="BUY" else close<o
    if not directional: return False
    if side=="BUY":
        checks=[close>prev, float(rsi.iloc[i])>=47,
                float(ema20.iloc[i])>=float(ema50.iloc[i]),
                int((recent["close"].astype(float)>recent["open"].astype(float)).sum())>=2]
    else:
        checks=[close<prev, float(rsi.iloc[i])<=53,
                float(ema20.iloc[i])<=float(ema50.iloc[i]),
                int((recent["close"].astype(float)<recent["open"].astype(float)).sum())>=2]
    return sum(bool(x) for x in checks)>=2

def get_adaptive_signal(h1,h4,m15,m5,d1=None,w1=None):
    """M5/M1 scalping signal. h1/h4 args remain for caller compatibility only."""
    hold=AdaptiveSignal("HOLD",0,0,0,0,False,"","LOW","Waiting for sufficient completed M5/M1 broker candles")
    if not all((_valid(m15,30),_valid(m5,25))):
        hold.details="Insufficient completed M5/M1 broker candles"
        return hold

    # No H1/H4 trend gate: choose direction from the completed M5 trend.
    c5,_,_,e20_5,e50_5,rsi5,atr5=_ind(m15)
    i5=len(m15)-1
    if not np.isfinite(atr5.iloc[i5]) or not np.isfinite(rsi5.iloc[i5]):
        hold.details="M5 indicator warm-up incomplete"
        return hold
    m5_bull=float(e20_5.iloc[i5])>float(e50_5.iloc[i5]) and float(c5.iloc[i5])>float(e20_5.iloc[i5])
    m5_bear=float(e20_5.iloc[i5])<float(e50_5.iloc[i5]) and float(c5.iloc[i5])<float(e20_5.iloc[i5])
    if m5_bull:
        side="BUY"
    elif m5_bear:
        side="SELL"
    else:
        hold.details="HOLD: M5 trend unclear or ranging"
        return hold

    setup=_setup(m15,side)
    if not setup:
        hold.details=f"HOLD: no valid M5 liquidity/pullback setup in {side} scalp trend"
        return hold
    setup_name,setup_points,structure_price=setup
    if not _m5_confirm(m5,side):
        hold.details=f"HOLD: {setup_name} found; waiting for M1 confirmation"
        return hold

    rsi=float(rsi5.iloc[i5])
    momentum=(42<=rsi<=76) if side=="BUY" else (24<=rsi<=58)
    if not momentum:
        hold.details=f"HOLD: {setup_name} confirmed but M5 RSI is outside the permitted scalp band (RSI14={rsi:.1f})"
        return hold

    score=min(100,35+setup_points+15+10)
    if score<MIN_ADAPTIVE_SCORE:
        hold.total_score=score
        hold.details=f"HOLD: {setup_name} score {score}/{MIN_ADAPTIVE_SCORE}"
        return hold

    m5_atr=float(atr5.iloc[i5])
    price=float(c5.iloc[i5])
    if not np.isfinite(m5_atr) or m5_atr<=0:
        hold.details="HOLD: invalid M5 ATR"
        return hold
    if side=="BUY":
        sl=min(float(structure_price),price-1.2*m5_atr)-0.15*m5_atr
        risk=price-sl
        tp=price+2.0*risk
    else:
        sl=max(float(structure_price),price+1.2*m5_atr)+0.15*m5_atr
        risk=sl-price
        tp=price-2.0*risk
    if risk<=0 or risk>3.5*m5_atr:
        hold.details=f"HOLD: stop distance invalid ({risk:.3f})"
        return hold

    try:
        from fundamental_gate import score_phase4
        macro_pts,news_block,news_reason,macro_details=score_phase4(side)
    except Exception as exc:
        macro_pts,news_block,news_reason,macro_details=0,True,f"Fundamental/news validation failed: {exc}","macro unavailable"
    if news_block:
        return AdaptiveSignal("HOLD",score,2,setup_points,0,True,news_reason,"BLOCKED",
            f"NEWS BLOCK: {news_reason}",setup_name,price,sl,tp,m5_atr)

    score=min(100,score+int(macro_pts)*2)
    return AdaptiveSignal(side,score,2,setup_points,int(macro_pts),False,"",
        "HIGH" if score>=85 else "MEDIUM",
        f"{setup_name}; M5 scalp trend aligned; M1 confirmed; M5 RSI14={rsi:.1f}; ATR14={m5_atr:.3f}; {macro_details}; SL/TP=structure + 2R",
        setup_name,price,sl,tp,m5_atr)

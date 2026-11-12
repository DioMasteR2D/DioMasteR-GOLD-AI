"""Adaptive Liquidity Hunter for XAUUSD.

Uses completed broker OHLC only. H4/H1 define directional bias; M15 identifies
liquidity sweep, BOS/retest, EMA pullback or breakout/retest; M5 confirms timing.
Fundamental/news gate is retained as a hard safety filter.
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
    c,h,l,e20,e50,rsi,atr=_ind(m15)
    i=len(m15)-1
    if i < 25 or not np.isfinite(atr.iloc[i]) or atr.iloc[i] <= 0:
        return None
    o=float(m15["open"].iloc[i]); close=float(c.iloc[i]); high=float(h.iloc[i]); low=float(l.iloc[i])
    a=float(atr.iloc[i]); prior_high=float(h.iloc[i-20:i].max()); prior_low=float(l.iloc[i-20:i].min())
    body=max(abs(close-o),a*0.02); lower_wick=min(o,close)-low; upper_wick=high-max(o,close)
    # Sweep: pierce a prior 20-bar extreme and close back inside with rejection.
    if side=="BUY" and low < prior_low and close > prior_low and lower_wick >= body*0.8:
        return ("LIQUIDITY_SWEEP", 30, low)
    if side=="SELL" and high > prior_high and close < prior_high and upper_wick >= body*0.8:
        return ("LIQUIDITY_SWEEP", 30, high)
    # BOS + retest: a prior close broke structure; current candle retests and holds it.
    prev_close=float(c.iloc[i-1]); prior_res=float(h.iloc[i-11:i-1].max()); prior_sup=float(l.iloc[i-11:i-1].min())
    if side=="BUY" and prev_close > prior_res and low <= prior_res and close > prior_res and close > o:
        return ("BOS_RETEST", 27, min(low,prior_res))
    if side=="SELL" and prev_close < prior_sup and high >= prior_sup and close < prior_sup and close < o:
        return ("BOS_RETEST", 27, max(high,prior_sup))
    # Trend pullback to EMA20/50 with a close back in trend direction.
    zone_low=min(float(e20.iloc[i]),float(e50.iloc[i])); zone_high=max(float(e20.iloc[i]),float(e50.iloc[i]))
    if side=="BUY" and low <= zone_high and close > float(e20.iloc[i]) and close > o:
        return ("EMA_PULLBACK", 23, low)
    if side=="SELL" and high >= zone_low and close < float(e20.iloc[i]) and close < o:
        return ("EMA_PULLBACK", 23, high)
    # Breakout and retest of a recent 12-bar range.
    range_high=float(h.iloc[i-13:i-1].max()); range_low=float(l.iloc[i-13:i-1].min())
    if side=="BUY" and prev_close > range_high and low <= range_high and close > range_high:
        return ("BREAKOUT_RETEST", 25, low)
    if side=="SELL" and prev_close < range_low and high >= range_low and close < range_low:
        return ("BREAKOUT_RETEST", 25, high)
    return None

def _m5_confirm(m5, side):
    if not _valid(m5, 22): return False
    c,h,l,_,_,rsi,atr=_ind(m5); i=len(m5)-1
    o=float(m5["open"].iloc[i]); close=float(c.iloc[i])
    if side=="BUY":
        return close>o and close>float(h.iloc[i-1]) and float(rsi.iloc[i])>=50
    return close<o and close<float(l.iloc[i-1]) and float(rsi.iloc[i])<=50

def get_adaptive_signal(h1,h4,m15,m5,d1=None,w1=None):
    hold=AdaptiveSignal("HOLD",0,0,0,0,False,"","LOW","Waiting for sufficient completed broker candles")
    if not all((_valid(h1,60),_valid(h4,55),_valid(m15,30),_valid(m5,25))):
        hold.details="Insufficient completed H1/H4/M15/M5 broker candles"
        return hold
    c1,hi1,lo1,e20_1,e50_1,rsi1,atr1=_ind(h1)
    c4,_,_,e20_4,e50_4,_,atr4=_ind(h4)
    i1=len(h1)-1; i4=len(h4)-1
    if not np.isfinite(atr1.iloc[i1]) or not np.isfinite(atr4.iloc[i4]):
        hold.details="ATR warm-up incomplete"; return hold
    h4_bull=float(c4.iloc[i4])>float(e50_4.iloc[i4]) and float(e20_4.iloc[i4])>float(e50_4.iloc[i4])
    h4_bear=float(c4.iloc[i4])<float(e50_4.iloc[i4]) and float(e20_4.iloc[i4])<float(e50_4.iloc[i4])
    h1_bull=float(e20_1.iloc[i1])>float(e50_1.iloc[i1]) and float(c1.iloc[i1])>float(e20_1.iloc[i1])
    h1_bear=float(e20_1.iloc[i1])<float(e50_1.iloc[i1]) and float(c1.iloc[i1])<float(e20_1.iloc[i1])
    if h4_bull and h1_bull: side="BUY"
    elif h4_bear and h1_bear: side="SELL"
    else:
        hold.details="HOLD: H4/H1 trend alignment absent or market ranging"
        return hold
    setup=_setup(m15,side)
    if not setup:
        hold.details=f"HOLD: no valid M15 liquidity/pullback setup in {side} trend"
        return hold
    setup_name,setup_points,structure_price=setup
    confirmed=_m5_confirm(m5,side)
    if not confirmed:
        hold.details=f"HOLD: {setup_name} found; waiting for M5 confirmation"
        return hold
    rsi=float(rsi1.iloc[i1]); atr=float(atr1.iloc[i1]); price=float(c1.iloc[i1])
    momentum=(50<=rsi<=72) if side=="BUY" else (28<=rsi<=50)
    if not momentum:
        hold.details=f"HOLD: {setup_name} confirmed but H1 RSI momentum is not aligned (RSI14={rsi:.1f})"
        return hold
    # Score is setup quality, not a win-probability percentage.
    score=35+setup_points+15+10
    score=min(100,score)
    if score<MIN_ADAPTIVE_SCORE:
        hold.total_score=score; hold.details=f"HOLD: {setup_name} score {score}/{MIN_ADAPTIVE_SCORE}; momentum not confirmed"
        return hold
    m15c,_,_,_,_,_,m15atr_series=_ind(m15)
    m15atr=float(m15atr_series.iloc[-1])
    price=float(m15c.iloc[-1])
    if not np.isfinite(m15atr) or m15atr<=0:
        hold.details="HOLD: invalid M15 ATR"; return hold
    # Structure-led stop with an M15 ATR safety buffer.
    if side=="BUY":
        sl=min(float(structure_price),price-1.2*m15atr)-0.15*m15atr
        risk=price-sl
        tp=price+2.0*risk
    else:
        sl=max(float(structure_price),price+1.2*m15atr)+0.15*m15atr
        risk=sl-price
        tp=price-2.0*risk
    if risk<=0 or risk>3.5*m15atr:
        hold.details=f"HOLD: stop distance invalid ({risk:.3f})"; return hold
    # Reuse the established macro/news evaluator. News remains an absolute block.
    try:
        from unified_engine import score_phase4
        macro_pts,news_block,news_reason,macro_details=score_phase4(side)
    except Exception as exc:
        macro_pts,news_block,news_reason,macro_details=0,True,f"Fundamental/news validation failed: {exc}","macro unavailable"
    if news_block:
        return AdaptiveSignal("HOLD",score,2,setup_points,0,True,news_reason,"BLOCKED",
            f"NEWS BLOCK: {news_reason}",setup_name,price,sl,tp,atr)
    # Macro is a quality modifier only; neutral macro does not veto technical setups.
    score=min(100,score+int(macro_pts)*2)
    return AdaptiveSignal(side,score,2,setup_points,int(macro_pts),False,"",
        "HIGH" if score>=85 else "MEDIUM",
        f"{setup_name}; H4/H1 aligned; M5 confirmed; RSI14={rsi:.1f}; ATR14={atr:.3f}; {macro_details}; SL/TP=structure + 2R",
        setup_name,price,sl,tp,atr)

"""Adaptive Liquidity Hunter for XAUUSD.

Uses completed broker OHLC only. H4/H1 EMA9/EMA21 define directional bias; M5 identifies
liquidity sweep, BOS/retest, EMA pullback or breakout/retest; M1 confirms timing.
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
    ema9=c.ewm(span=9, adjust=False).mean()
    ema21=c.ewm(span=21, adjust=False).mean()
    delta=c.diff()
    gain=delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss=(-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rsi=100-(100/(1+gain/loss.replace(0,np.nan)))
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    return c,h,l,ema9,ema21,rsi,atr

def _setup(m15, side):
    """Fast M5 entry setup; inspect the latest six CLOSED M5 candles."""
    c,h,l,e9,e21,rsi,atr=_ind(m15)
    last=len(m15)-1
    if last < 25 or not np.isfinite(atr.iloc[last]) or atr.iloc[last] <= 0:
        return None
    # Prefer the newest valid setup, but do not discard a setup merely because
    # the next one or two closed M5 candles are the confirmation/retest candle.
    for i in range(last, max(24,last-6), -1):
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
        zone_low=min(float(e9.iloc[i]),float(e21.iloc[i])); zone_high=max(float(e9.iloc[i]),float(e21.iloc[i]))
        recent_low=float(l.iloc[max(0,i-6):i+1].min()); recent_high=float(h.iloc[max(0,i-6):i+1].max())
        touch_buffer=0.15*a
        if side=="BUY" and recent_low <= zone_high+touch_buffer and close > float(e9.iloc[i]) and close > o:
            return ("EMA_PULLBACK", 23, min(recent_low, float(e9.iloc[i])))
        if side=="SELL" and recent_high >= zone_low-touch_buffer and close < float(e9.iloc[i]) and close < o:
            return ("EMA_PULLBACK", 23, max(recent_high, float(e9.iloc[i])))
        range_high=float(h.iloc[max(0,i-13):i-1].max()); range_low=float(l.iloc[max(0,i-13):i-1].min())
        if side=="BUY" and prev_close > range_high and low <= range_high and close > range_high:
            return ("BREAKOUT_RETEST", 25, low)
        if side=="SELL" and prev_close < range_low and high >= range_low and close < range_low:
            return ("BREAKOUT_RETEST", 25, high)
    return None

def _setup_diagnostics(m15, side):
    """Explain every M5 setup predicate and its input values; read-only diagnostics."""
    c,h,l,e9,e21,rsi,atr=_ind(m15)
    last=len(m15)-1
    if last < 25:
        return f"M5_SCAN side={side} insufficient_bars={len(m15)}"
    rows=[]
    for i in range(last, max(24,last-6), -1):
        if not np.isfinite(atr.iloc[i]) or float(atr.iloc[i]) <= 0:
            rows.append(f"bar{i}:invalid_atr")
            continue
        o=float(m15["open"].iloc[i]); close=float(c.iloc[i]); high=float(h.iloc[i]); low=float(l.iloc[i])
        a=float(atr.iloc[i]); prev_close=float(c.iloc[i-1])
        prior_high=float(h.iloc[i-20:i].max()); prior_low=float(l.iloc[i-20:i].min())
        body=max(abs(close-o),a*0.02); lower_wick=min(o,close)-low; upper_wick=high-max(o,close)
        sweep=(low < prior_low and close > prior_low and lower_wick >= body*0.8) if side=="BUY" else (high > prior_high and close < prior_high and upper_wick >= body*0.8)
        prior_res=float(h.iloc[i-11:i-1].max()); prior_sup=float(l.iloc[i-11:i-1].min())
        bos=(prev_close > prior_res and low <= prior_res and close > prior_res and close > o) if side=="BUY" else (prev_close < prior_sup and high >= prior_sup and close < prior_sup and close < o)
        ema9=float(e9.iloc[i]); ema21=float(e21.iloc[i])
        zone_low=min(ema9,ema21); zone_high=max(ema9,ema21)
        recent_low=float(l.iloc[max(0,i-6):i+1].min()); recent_high=float(h.iloc[max(0,i-6):i+1].max())
        buffer=0.15*a
        ema=(recent_low <= zone_high+buffer and close > ema9 and close > o) if side=="BUY" else (recent_high >= zone_low-buffer and close < ema9 and close < o)
        range_high=float(h.iloc[max(0,i-13):i-1].max()); range_low=float(l.iloc[max(0,i-13):i-1].min())
        breakout=(prev_close > range_high and low <= range_high and close > range_high) if side=="BUY" else (prev_close < range_low and high >= range_low and close < range_low)
        stamp=m15["timestamp"].iloc[i] if "timestamp" in m15.columns else i
        rows.append(
            f"{stamp}:O={o:.2f},H={high:.2f},L={low:.2f},C={close:.2f},"
            f"prevC={prev_close:.2f},ATR={a:.3f},body={body:.3f},"
            f"wickU={upper_wick:.3f},wickL={lower_wick:.3f},"
            f"priorH={prior_high:.2f},priorL={prior_low:.2f},"
            f"res={prior_res:.2f},sup={prior_sup:.2f},"
            f"EMA9={ema9:.2f},EMA21={ema21:.2f},"
            f"recentH={recent_high:.2f},recentL={recent_low:.2f},"
            f"rangeH={range_high:.2f},rangeL={range_low:.2f},"
            f"sweep={int(sweep)},bos={int(bos)},ema_pullback={int(ema)},breakout_retest={int(breakout)}"
        )
    return f"M5_SCAN side={side} " + " | ".join(rows)

def _m1_confirmation_diagnostics(m1, side):
    """Read-only explanation of the exact M1 confirmation checks."""
    if not _valid(m1, 22):
        return f"M1_CONFIRM insufficient_bars={len(m1) if isinstance(m1, pd.DataFrame) else 0}/22"
    c,h,l,e9,e21,rsi,atr=_ind(m1); i=len(m1)-1
    recent=m1.iloc[i-2:i+1]
    o=float(m1["open"].iloc[i]); close=float(c.iloc[i]); prev=float(c.iloc[i-1])
    directional=close>o if side=="BUY" else close<o
    if side=="BUY":
        checks=[close>prev, float(rsi.iloc[i])>=47,
                float(e9.iloc[i])>=float(e21.iloc[i]),
                int((recent["close"].astype(float)>recent["open"].astype(float)).sum())>=2]
    else:
        checks=[close<prev, float(rsi.iloc[i])<=53,
                float(e9.iloc[i])<=float(e21.iloc[i]),
                int((recent["close"].astype(float)<recent["open"].astype(float)).sum())>=2]
    return (f"M1_CONFIRM side={side} directional={int(directional)} "
            f"close_vs_prev={int(checks[0])} rsi={float(rsi.iloc[i]):.1f} rsi_ok={int(checks[1])} "
            f"ema9={float(e9.iloc[i]):.3f} ema21={float(e21.iloc[i]):.3f} ema_ok={int(checks[2])} "
            f"recent_directional={int((recent['close'].astype(float)>recent['open'].astype(float)).sum()) if side=='BUY' else int((recent['close'].astype(float)<recent['open'].astype(float)).sum())}/3 "
            f"recent_ok={int(checks[3])} passed={sum(bool(x) for x in checks)}/4 required=2")

def _m5_confirm(m5, side):
    """Fast M1 timing confirmation: latest closed candle plus recent momentum."""
    if not _valid(m5, 22): return False
    c,h,l,ema9,ema21,rsi,atr=_ind(m5); i=len(m5)-1
    # Use a short 3-candle window so a valid M1 impulse is not lost to one
    # small pause candle. The latest candle must still close in trade direction.
    recent=m5.iloc[i-2:i+1]
    o=float(m5["open"].iloc[i]); close=float(c.iloc[i]); prev=float(c.iloc[i-1])
    directional=close>o if side=="BUY" else close<o
    if not directional: return False
    if side=="BUY":
        checks=[close>prev, float(rsi.iloc[i])>=47,
                float(ema9.iloc[i])>=float(ema21.iloc[i]),
                int((recent["close"].astype(float)>recent["open"].astype(float)).sum())>=2]
    else:
        checks=[close<prev, float(rsi.iloc[i])<=53,
                float(ema9.iloc[i])<=float(ema21.iloc[i]),
                int((recent["close"].astype(float)<recent["open"].astype(float)).sum())>=2]
    return sum(bool(x) for x in checks)>=2

def get_adaptive_signal(h1,h4,m15,m5,d1=None,w1=None):
    hold=AdaptiveSignal("HOLD",0,0,0,0,False,"","LOW","Waiting for sufficient completed broker candles")
    if not all((_valid(h1,60),_valid(h4,55),_valid(m15,30),_valid(m5,25))):
        hold.details="Insufficient completed H1/H4/M5/M1 broker candles"
        return hold
    c1,hi1,lo1,e9_1,e21_1,rsi1,atr1=_ind(h1)
    c4,_,_,e9_4,e21_4,_,atr4=_ind(h4)
    i1=len(h1)-1; i4=len(h4)-1
    if not np.isfinite(atr1.iloc[i1]) or not np.isfinite(atr4.iloc[i4]):
        hold.details="ATR warm-up incomplete"; return hold
    # Directional bias is defined by the EMA9/EMA21 relationship only.
    # Requiring price to also be above/below EMA9 incorrectly turns normal
    # pullbacks into a neutral trend and blocks otherwise aligned H4/H1 setups.
    h4_bull=float(e9_4.iloc[i4])>float(e21_4.iloc[i4])
    h4_bear=float(e9_4.iloc[i4])<float(e21_4.iloc[i4])
    h1_bull=float(e9_1.iloc[i1])>float(e21_1.iloc[i1])
    h1_bear=float(e9_1.iloc[i1])<float(e21_1.iloc[i1])
    if h4_bull and h1_bull: side="BUY"
    elif h4_bear and h1_bear: side="SELL"
    else:
        hold.details="HOLD: H4/H1 trend alignment absent or market ranging"
        return hold
    setup=_setup(m15,side)
    if not setup:
        scan=_setup_diagnostics(m15,side)
        hold.details=f"HOLD: no valid M5 liquidity/pullback setup in {side} trend; {scan}"
        return hold
    setup_name,setup_points,structure_price=setup
    confirmed=_m5_confirm(m5,side)
    if not confirmed:
        m1_diag=_m1_confirmation_diagnostics(m5,side)
        hold.details=f"HOLD: {setup_name} found; waiting for M1 confirmation; {m1_diag}"
        return hold
    rsi=float(rsi1.iloc[i1]); atr=float(atr1.iloc[i1]); price=float(c1.iloc[i1])
    # Wider neutral bands avoid rejecting otherwise aligned trends for a small
    # RSI pullback; extreme momentum remains filtered to avoid chasing exhaustion.
    momentum=(45<=rsi<=75) if side=="BUY" else (25<=rsi<=55)
    if not momentum:
        hold.details=f"HOLD: {setup_name} confirmed but H1 RSI is outside the permitted trend band (RSI14={rsi:.1f})"
        return hold
    # Score is setup quality, not a win-probability percentage.
    score=35+setup_points+15+10
    score=min(100,score)
    if score<MIN_ADAPTIVE_SCORE:
        hold.total_score=score; hold.details=f"HOLD: {setup_name} score {score}/{MIN_ADAPTIVE_SCORE}; momentum not confirmed"
        return hold
    m15c,_,_,_,_,_,m15atr_series=_ind(m15)  # M5 ATR for fast scalping stops
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
        from fundamental_gate import score_phase4
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
        f"{setup_name}; H4/H1 aligned; M1 confirmed; RSI14={rsi:.1f}; ATR14={atr:.3f}; {macro_details}; SL/TP=structure + 2R",
        setup_name,price,sl,tp,atr)

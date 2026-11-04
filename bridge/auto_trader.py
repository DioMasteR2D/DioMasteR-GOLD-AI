"""Deterministic XAUUSD M5 strategy engine inspired by the selected forex-gold architecture.
Independent breakout and liquidity-reversal candidates feed a shared risk gate.
This is original implementation; no source code copied from MooreSi/forex-gold.
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import math

@dataclass
class Signal:
    side: str
    strategy: str
    score: float
    entry: float
    stop: float
    target: float
    reason: str

def ema(values: List[float], period: int) -> float:
    if len(values) < period: return float("nan")
    k=2.0/(period+1.0); v=sum(values[:period])/period
    for x in values[period:]: v=x*k+v*(1-k)
    return v

def atr(rates, period=14):
    if len(rates)<period+1: return float("nan")
    tr=[]
    for i in range(1,len(rates)):
        h,l,c0=float(rates[i]["high"]),float(rates[i]["low"]),float(rates[i-1]["close"])
        tr.append(max(h-l,abs(h-c0),abs(l-c0)))
    return sum(tr[-period:])/period

def adx_proxy(rates, period=14):
    if len(rates)<period+1: return 0.0
    plus=minus=0.0
    for i in range(-period,0):
        up=float(rates[i]["high"])-float(rates[i-1]["high"])
        dn=float(rates[i-1]["low"])-float(rates[i]["low"])
        plus+=max(up,0) if up>dn else 0
        minus+=max(dn,0) if dn>up else 0
    return 100*abs(plus-minus)/max(plus+minus,1e-9)

def _candidate(side, name, score, entry, stop, target, reason):
    if side=="BUY" and not (stop<entry<target): return None
    if side=="SELL" and not (target<entry<stop): return None
    if abs(entry-stop)<=0: return None
    if abs(target-entry)/abs(entry-stop)<1.5: return None
    return Signal(side,name,score,entry,stop,target,reason)

def evaluate(rates, bid: float, ask: float, spread_limit: float=1.2) -> Optional[Signal]:
    """Evaluate only completed M5 candles; caller supplies at least 80 rates."""
    if len(rates)<80 or bid<=0 or ask<bid or ask-bid>spread_limit: return None
    closed=rates[:-1]
    closes=[float(x["close"]) for x in closed]
    highs=[float(x["high"]) for x in closed]
    lows=[float(x["low"]) for x in closed]
    a=atr(closed)
    if not math.isfinite(a) or a<=0: return None
    fast,slow=ema(closes[-80:],20),ema(closes[-100:] if len(closes)>=100 else closes,50)
    last=closed[-1]; prev=closed[-2]
    c=float(last["close"]); h=float(last["high"]); l=float(last["low"])
    candidates=[]
    # Breakout engine: trend-aligned close beyond the prior 20-bar range, with ADX proxy.
    prior_hi=max(highs[-21:-1]); prior_lo=min(lows[-21:-1]); trend=adx_proxy(closed)
    if fast>slow and c>prior_hi and trend>=18:
        s=_candidate("BUY","BREAKOUT",min(0.95,0.65+trend/200),ask,ask-1.5*a,ask+2.5*a,"M5 range breakout + EMA20/50 trend + directional strength")
        if s:candidates.append(s)
    if fast<slow and c<prior_lo and trend>=18:
        s=_candidate("SELL","BREAKOUT",min(0.95,0.65+trend/200),bid,bid+1.5*a,bid-2.5*a,"M5 range breakdown + EMA20/50 trend + directional strength")
        if s:candidates.append(s)
    # Reversal engine: liquidity sweep of recent swing followed by close back inside.
    swing_hi=max(highs[-12:-1]); swing_lo=min(lows[-12:-1])
    body=abs(c-float(last["open"]))
    if float(last["low"])<swing_lo and c>swing_lo and c>float(last["open"]) and body>=0.15*a:
        s=_candidate("BUY","LIQUIDITY_REVERSAL",0.70,ask,ask-1.35*a,ask+2.1*a,"Sell-side liquidity sweep reclaimed with bullish displacement")
        if s:candidates.append(s)
    if float(last["high"])>swing_hi and c<swing_hi and c<float(last["open"]) and body>=0.15*a:
        s=_candidate("SELL","LIQUIDITY_REVERSAL",0.70,bid,bid+1.35*a,bid-2.1*a,"Buy-side liquidity sweep rejected with bearish displacement")
        if s:candidates.append(s)
    if not candidates:return None
    candidates.sort(key=lambda x:x.score,reverse=True)
    if len(candidates)>1 and candidates[0].side!=candidates[1].side:
        return None
    return candidates[0]

def risk_sized_volume(equity: float, entry: float, stop: float, contract_size: float,
                      volume_min: float, volume_step: float, volume_max: float,
                      configured_max: float, risk_fraction: float=0.0025) -> float:
    """Size using broker contract size and stop distance; floor to broker volume step."""
    if min(equity,entry,contract_size,volume_min,volume_step,volume_max,configured_max)<=0:return 0.0
    risk_cash=equity*risk_fraction
    per_lot=abs(entry-stop)*contract_size
    if per_lot<=0:return 0.0
    raw=min(risk_cash/per_lot,configured_max,volume_max,5.0/contract_size)
    steps=math.floor((raw+1e-12)/volume_step)
    volume=steps*volume_step
    if volume+1e-10<volume_min:return 0.0
    return round(volume,8)

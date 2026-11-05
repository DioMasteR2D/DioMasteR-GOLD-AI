"""DioMasteR GOLD AI bridge for TickerAll MT5 DEMO."""
import os, hmac, uuid
from typing import Optional
import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

TA_TOKEN=os.getenv("TICKERALL_API_KEY","").strip()
TA_BASE=os.getenv("TICKERALL_API_BASE","https://api.tickerall.com").rstrip("/")
ACCOUNT_ID=os.getenv("TICKERALL_ACCOUNT_ID","").strip()
BROKER_SERVER=os.getenv("TICKERALL_SERVER","VantageMarkets-Demo").strip()
BRIDGE_TOKEN=os.getenv("DIO_BRIDGE_TOKEN","")
EXECUTION_ENABLED=os.getenv("DIO_MT5_DEMO_EXECUTION_ENABLED","false").lower()=="true"
SYMBOLS={x.strip() for x in os.getenv("DIO_MT5_ALLOWED_SYMBOLS","XAUUSD").split(",") if x.strip()}
MAX_VOLUME=float(os.getenv("DIO_MT5_MAX_VOLUME","0.01"))
MAX_RISK_FRACTION=float(os.getenv("DIO_MT5_MAX_RISK_FRACTION","0.0025"))
MAX_BOT_POSITIONS=int(os.getenv("DIO_MT5_MAX_POSITIONS","3"))
app=FastAPI(title="DioMasteR GOLD AI TickerAll DEMO Bridge",version="2.0.0")

class Order(BaseModel):
    symbol:str=Field(min_length=3,max_length=32)
    side:str
    volume:float=Field(gt=0,le=MAX_VOLUME)
    stop_loss:float=Field(gt=0)
    take_profit:float=Field(gt=0)
    client_order_id:str=Field(min_length=8,max_length=64)

def auth(value:Optional[str]):
    if not BRIDGE_TOKEN: raise HTTPException(503,"DIO_BRIDGE_TOKEN is not configured")
    got=(value or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got,BRIDGE_TOKEN): raise HTTPException(401,"Unauthorized")

def configured():
    if not TA_TOKEN: raise HTTPException(503,"TickerAll API key is not configured")
    if not BRIDGE_TOKEN: raise HTTPException(503,"Bridge auth is not configured")

async def ta(method,path,body=None,idem=False):
    configured()
    headers={"Authorization":"Bearer "+TA_TOKEN,"Accept":"application/json"}
    if body is not None: headers["Content-Type"]="application/json"
    if idem: headers["Idempotency-Key"]=str(uuid.uuid4())
    async with httpx.AsyncClient(timeout=25) as client:
        r=await client.request(method,TA_BASE+path,headers=headers,json=body)
    if r.status_code>=400:
        try:
            data=r.json(); detail=data.get("message") or data.get("error") or str(data)
        except Exception: detail=r.text[:400]
        raise HTTPException(r.status_code,str(detail)[:500])
    if not r.content: return {}
    return r.json()

async def account():
    data=await ta("GET","/v1/accounts")
    rows=data if isinstance(data,list) else data.get("accounts",[])
    if ACCOUNT_ID:
        match=next((x for x in rows if str(x.get("id"))==ACCOUNT_ID),None)
    else:
        candidates=[x for x in rows if str(x.get("broker","")).lower()=="mt5"
          and x.get("isDemo") is True
          and str(x.get("server","")).lower()==BROKER_SERVER.lower()]
        if len(candidates)>1: raise HTTPException(409,"More than one matching Vantage DEMO account; set TICKERALL_ACCOUNT_ID")
        match=candidates[0] if candidates else None
    if not match: raise HTTPException(503,"Vantage DEMO account not found in this TickerAll API key")
    if match.get("isDemo") is not True: raise HTTPException(403,"TickerAll did not verify this as DEMO")
    if str(match.get("broker","")).lower()!="mt5": raise HTTPException(403,"Only MT5 is allowed")
    if str(match.get("server","")).lower()!=BROKER_SERVER.lower(): raise HTTPException(403,"Unexpected broker server")
    return match

async def account_detail():
    row=await account()
    detail=await ta("GET",f"/v1/accounts/{row['id']}")
    if detail.get("isDemo") is not True: raise HTTPException(403,"DEMO verification failed; trading blocked")
    online=str(detail.get("status","")).lower() in ("online","connected")
    if not online: raise HTTPException(503,"Vantage DEMO connection is offline/cold; reconnect it in TickerAll")
    return row,detail

def choose_symbol(symbols):
    available=symbols or []
    for preferred in ("XAUUSD","XAUUSDm","GOLD","GOLDm"):
        if preferred in available: return preferred
    for s in available:
        if "XAUUSD" in str(s).upper() or str(s).upper().startswith("GOLD"): return str(s)
    return next(iter(SYMBOLS), "XAUUSD")

@app.get("/health")
def health():
    return {"ok":True,"service":"diomaster-tickerall-demo-bridge","bridge_version":"2.0.0"}

@app.get("/v1/status")
async def status(authorization:Optional[str]=Header(default=None)):
    auth(authorization); row,detail=await account_detail()
    symbols_data=await ta("GET",f"/v1/accounts/{row['id']}/symbols")
    available=symbols_data.get("symbols",[])
    symbol=choose_symbol(available)
    acc=detail.get("account",{})
    return {"service":"DioMasteR GOLD AI","bridge_version":"2.0.0",
      "terminal_connected":True,"account_mode":"DEMO",
      "account_login":str(row.get("accountNumber","")),
      "server":str(row.get("server","")),"currency":str(acc.get("currency","USD")),
      "balance":float(acc.get("balance") or 0),"equity":float(acc.get("equity") or 0),
      "execution_enabled":EXECUTION_ENABLED,"allowed_symbols":[symbol],
      "provider":"TickerAll","connection_hot":bool(row.get("hot",False)),
      "always_hot":bool(row.get("alwaysHot",False))}

@app.get("/v1/quote/{symbol}")
async def quote(symbol:str,authorization:Optional[str]=Header(default=None)):
    auth(authorization); row,_=await account_detail()
    symbols_data=await ta("GET",f"/v1/accounts/{row['id']}/symbols")
    available=symbols_data.get("symbols",[])
    if symbol not in available: raise HTTPException(404,"Broker-native symbol not found; inspect /v1/status allowed_symbols")
    candles=await ta("GET",f"/v1/accounts/{row['id']}/candles?symbol={symbol}&timeframe=M1&hours=1")
    bars=candles.get("candles",[])
    if not bars: raise HTTPException(503,"No broker M1 candles available")
    last=bars[-1]; bid=float(last.get("close") or last.get("bid") or 0)
    ts=float(last.get("timestamp") or 0)
    if bid<=0: raise HTTPException(503,"Invalid broker candle price")
    # TickerAll REST candles provide OHLC but not a bid/ask tick. Return last M1 close
    # as an indicative reference only; order placement is still broker market execution.
    return {"symbol":symbol,"bid":bid,"ask":bid,"time":ts,
      "quote_source":"last_M1_candle_close_not_live_tick","account_mode":"DEMO"}

@app.get("/v1/positions")
async def positions(authorization:Optional[str]=Header(default=None)):
    auth(authorization); row,_=await account_detail()
    data=await ta("GET",f"/v1/accounts/{row['id']}/positions")
    rows=data.get("positions",[]) if isinstance(data,dict) else data
    result=[]
    for p in rows:
        result.append({"ticket":int(p.get("ticket") or 0),"symbol":p.get("symbol"),
          "type":0 if str(p.get("side","")).upper()=="BUY" else 1,
          "volume":float(p.get("volume") or 0),"price_open":float(p.get("entryPrice") or 0),
          "price_current":float(p.get("currentPrice") or 0),"profit":float(p.get("profit") or 0),
          "sl":float(p.get("stopLoss") or 0),"tp":float(p.get("takeProfit") or 0),
          "comment":p.get("comment","")})
    return {"account_mode":"DEMO","positions":result}

@app.post("/v1/order")
async def order(req:Order,authorization:Optional[str]=Header(default=None)):
    auth(authorization); row,detail=await account_detail()
    if not EXECUTION_ENABLED: raise HTTPException(423,"DEMO execution is disabled until read-only connection tests pass")
    if req.symbol not in SYMBOLS and req.symbol not in (await ta("GET",f"/v1/accounts/{row['id']}/symbols")).get("symbols",[]):
        raise HTTPException(403,"Symbol is not available on this Vantage account")
    side=req.side.upper()
    if side not in ("BUY","SELL"): raise HTTPException(422,"side must be BUY or SELL")
    if req.volume>MAX_VOLUME: raise HTTPException(422,"Volume exceeds configured cap")
    q=await quote(req.symbol,authorization="Bearer "+BRIDGE_TOKEN)
    ref=float(q["bid"])
    sl=float(req.stop_loss); tp=float(req.take_profit)
    if (side=="BUY" and not sl<ref<tp) or (side=="SELL" and not tp<ref<sl):
        raise HTTPException(422,"SL/TP direction does not match latest M1 reference price")
    equity=float((detail.get("account") or {}).get("equity") or 0)
    risk=abs(ref-sl)*req.volume*100.0
    if equity<=0 or risk>equity*MAX_RISK_FRACTION:
        raise HTTPException(422,"Order exceeds configured 0.25% equity risk cap (conservative XAU contract estimate)")
    pdata=await ta("GET",f"/v1/accounts/{row['id']}/positions")
    open_rows=pdata.get("positions",[])
    bot=[p for p in open_rows if str(p.get("comment","")).startswith("DioMasteR")]
    if len(bot)>=MAX_BOT_POSITIONS: raise HTTPException(423,f"Maximum of {MAX_BOT_POSITIONS} bot positions reached")
    body={"type":"market","symbol":req.symbol,"side":side,"volume":req.volume,
      "stopLoss":sl,"takeProfit":tp,"comment":"DioMasteR "+req.client_order_id[-16:]}
    result=await ta("POST",f"/v1/accounts/{row['id']}/orders",body,idem=True)
    return {"ok":True,"account_mode":"DEMO","symbol":req.symbol,"side":side,
      "volume":req.volume,"order":int(result.get("ticket") or 0),"deal":0,
      "price":float(result.get("price") or ref),"retcode":10009 if result.get("status")=="open" else 0,
      "comment":result.get("status","submitted"),"client_order_id":req.client_order_id}

@app.post("/v1/positions/{ticket}/close")
async def close(ticket:int,authorization:Optional[str]=Header(default=None)):
    auth(authorization); row,_=await account_detail()
    if not EXECUTION_ENABLED: raise HTTPException(423,"DEMO execution disabled")
    pdata=await ta("GET",f"/v1/accounts/{row['id']}/positions")
    p=next((x for x in pdata.get("positions",[]) if int(x.get("ticket") or 0)==ticket),None)
    if not p: raise HTTPException(404,"Position not found")
    if not str(p.get("comment","")).startswith("DioMasteR"):
        raise HTTPException(403,"Only DioMasteR bot positions can be closed")
    result=await ta("DELETE",f"/v1/accounts/{row['id']}/positions/{ticket}",{},idem=True)
    return {"ok":bool(result.get("closed")),"account_mode":"DEMO","ticket":ticket,
      "deal":result.get("dealTicket"),"result":result}

@app.post("/v1/auto/start")
async def auto_start(authorization:Optional[str]=Header(default=None)):
    auth(authorization); await account_detail()
    raise HTTPException(501,"Automatic strategy loop is not implemented yet; manual DEMO orders only")

@app.get("/v1/auto/status")
async def auto_status(authorization:Optional[str]=Header(default=None)):
    auth(authorization); await account_detail()
    return {"running":False,"supported":False,"last_action":"NOT_IMPLEMENTED","account_mode":"DEMO"}

@app.post("/v1/auto/stop")
async def auto_stop(authorization:Optional[str]=Header(default=None)):
    auth(authorization)
    return {"running":False,"supported":False,"message":"No cloud auto loop is running"}

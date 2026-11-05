"""DioMasteR GOLD AI cloud bridge for MetaApi. DEMO-only; fail-closed."""
import os, hmac, uuid
from typing import Optional
import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

META_TOKEN=os.getenv("METAAPI_TOKEN","")
ACCOUNT_ID=os.getenv("METAAPI_ACCOUNT_ID","")
META_BASE=os.getenv("METAAPI_CLIENT_API","https://mt-client-api-v1.new-york.agiliumtrade.ai").rstrip("/")
BRIDGE_TOKEN=os.getenv("DIO_BRIDGE_TOKEN","")
EXECUTION_ENABLED=os.getenv("DIO_MT5_DEMO_EXECUTION_ENABLED","false").lower()=="true"
SYMBOLS={x.strip() for x in os.getenv("DIO_MT5_ALLOWED_SYMBOLS","XAUUSD").split(",") if x.strip()}
MAX_VOLUME=float(os.getenv("DIO_MT5_MAX_VOLUME","0.01"))
MAX_RISK_FRACTION=float(os.getenv("DIO_MT5_MAX_RISK_FRACTION","0.0025"))
MAGIC=int(os.getenv("DIO_MT5_MAGIC","26051105"))
app=FastAPI(title="DioMasteR GOLD AI MetaApi DEMO Bridge",version="1.0.0")

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
    if not META_TOKEN or not ACCOUNT_ID: raise HTTPException(503,"MetaApi account is not configured")
    if not BRIDGE_TOKEN: raise HTTPException(503,"Bridge auth is not configured")

async def api(method,path,body=None):
    configured()
    headers={"auth-token":META_TOKEN,"Accept":"application/json"}
    async with httpx.AsyncClient(timeout=20) as client:
        r=await client.request(method,META_BASE+path,headers=headers,json=body)
    if r.status_code>=400:
        detail=r.text[:600]
        raise HTTPException(502,f"MetaApi {r.status_code}: {detail}")
    return r.json() if r.content else {}

def basepath():
    return f"/users/current/accounts/{ACCOUNT_ID}"

async def demo_account():
    info=await api("GET",basepath()+"/account-information")
    mode=str(info.get("type") or info.get("tradeMode") or "").upper()
    if mode not in ("ACCOUNT_TRADE_MODE_DEMO","DEMO"):
        raise HTTPException(403,"DEMO account not verified by MetaApi; all trading blocked")
    state=await api("GET",basepath()+"/connection-state")
    connected=bool(state.get("connected") or state.get("connectedToBroker"))
    if not connected:
        raise HTTPException(503,"MetaApi terminal is not connected to Vantage")
    return info,state

@app.get("/health")
def health():
    return {"ok":True,"service":"diomaster-metaapi-demo-bridge","execution_enabled":EXECUTION_ENABLED}

@app.get("/v1/status")
async def status(authorization:Optional[str]=Header(default=None)):
    auth(authorization); info,state=await demo_account()
    return {"service":"DioMasteR GOLD AI","bridge_version":"1.0.0",
      "terminal_connected":True,"account_mode":"DEMO",
      "account_login":str(info.get("login","")),"server":str(info.get("broker","")),
      "currency":str(info.get("currency","USD")),"balance":float(info.get("balance",0)),
      "equity":float(info.get("equity",0)),"execution_enabled":EXECUTION_ENABLED,
      "allowed_symbols":sorted(SYMBOLS),"connection_state":state}

@app.get("/v1/quote/{symbol}")
async def quote(symbol:str,authorization:Optional[str]=Header(default=None)):
    auth(authorization); await demo_account()
    if symbol not in SYMBOLS: raise HTTPException(403,"Symbol is not allow-listed")
    p=await api("GET",basepath()+f"/symbols/{symbol}/current-price")
    bid=float(p.get("bid",0)); ask=float(p.get("ask",0))
    if bid<=0 or ask<=0 or ask<bid: raise HTTPException(503,"Broker quote unavailable")
    return {"symbol":symbol,"bid":bid,"ask":ask,"time":p.get("time"),"account_mode":"DEMO"}

@app.get("/v1/positions")
async def positions(authorization:Optional[str]=Header(default=None)):
    auth(authorization); await demo_account()
    rows=await api("GET",basepath()+"/positions")
    result=[]
    for p in (rows if isinstance(rows,list) else rows.get("positions",[])):
        result.append({"ticket":int(p.get("id") or p.get("ticket") or 0),
          "symbol":p.get("symbol"),"type":0 if str(p.get("type","")).upper() in ("POSITION_TYPE_BUY","BUY") else 1,
          "volume":float(p.get("volume",0)),"price_open":float(p.get("openPrice",0)),
          "price_current":float(p.get("currentPrice",0)),"profit":float(p.get("profit",0)),
          "sl":float(p.get("stopLoss",0) or 0),"tp":float(p.get("takeProfit",0) or 0),
          "magic":int(p.get("magic",0) or 0)})
    return {"account_mode":"DEMO","positions":result}

@app.post("/v1/order")
async def order(req:Order,authorization:Optional[str]=Header(default=None)):
    auth(authorization); info,_=await demo_account()
    if not EXECUTION_ENABLED: raise HTTPException(423,"DEMO execution disabled until MetaApi setup is verified")
    if req.symbol not in SYMBOLS: raise HTTPException(403,"Symbol is not allow-listed")
    side=req.side.upper()
    if side not in ("BUY","SELL"): raise HTTPException(422,"side must be BUY or SELL")
    if req.volume>MAX_VOLUME: raise HTTPException(422,"Volume exceeds configured cap")
    spec=await api("GET",basepath()+f"/symbols/{req.symbol}/specification")
    vmin=float(spec.get("minVolume",0.01)); vmax=float(spec.get("maxVolume",MAX_VOLUME)); step=float(spec.get("volumeStep",0.01))
    if req.volume<vmin or req.volume>min(vmax,MAX_VOLUME) or abs(round(req.volume/step)*step-req.volume)>1e-8:
        raise HTTPException(422,f"Volume must respect broker min/step ({vmin}/{step})")
    q=await api("GET",basepath()+f"/symbols/{req.symbol}/current-price")
    bid=float(q.get("bid",0)); ask=float(q.get("ask",0)); entry=ask if side=="BUY" else bid
    sl=float(req.stop_loss); tp=float(req.take_profit)
    if entry<=0 or (side=="BUY" and not sl<entry<tp) or (side=="SELL" and not tp<entry<sl):
        raise HTTPException(422,"Invalid SL/TP direction for current broker quote")
    # Conservative XAU risk approximation. MetaApi/broker remains final margin/risk authority.
    contract=float(spec.get("contractSize",100) or 100)
    risk=abs(entry-sl)*req.volume*contract
    equity=float(info.get("equity",0))
    if equity<=0 or risk>equity*MAX_RISK_FRACTION:
        raise HTTPException(422,"Order exceeds configured 0.25% equity risk cap")
    body={"actionType":"ORDER_TYPE_BUY" if side=="BUY" else "ORDER_TYPE_SELL",
      "symbol":req.symbol,"volume":req.volume,"stopLoss":sl,"takeProfit":tp,
      "stopLossUnits":"ABSOLUTE_PRICE","takeProfitUnits":"ABSOLUTE_PRICE",
      "comment":"DioMasteR DEMO "+req.client_order_id[-12:]}
    result=await api("POST",basepath()+"/trade",body)
    if int(result.get("numericCode",0))!=10009:
        raise HTTPException(502,{"message":"MetaApi did not confirm order completion","result":result})
    return {"ok":True,"account_mode":"DEMO","symbol":req.symbol,"side":side,"volume":req.volume,
      "order":int(result.get("orderId",0) or 0),"deal":0,"price":entry,
      "retcode":10009,"comment":result.get("message","Request completed"),
      "client_order_id":req.client_order_id}

@app.post("/v1/positions/{ticket}/close")
async def close(ticket:int,authorization:Optional[str]=Header(default=None)):
    auth(authorization); await demo_account()
    if not EXECUTION_ENABLED: raise HTTPException(423,"DEMO execution disabled")
    rows=await api("GET",basepath()+"/positions")
    rows=rows if isinstance(rows,list) else rows.get("positions",[])
    p=next((x for x in rows if int(x.get("id") or x.get("ticket") or 0)==ticket),None)
    if p is None: raise HTTPException(404,"Position not found")
    if int(p.get("magic",0) or 0)!=MAGIC: raise HTTPException(403,"Only DioMasteR bot positions can be closed")
    result=await api("POST",basepath()+"/trade",{"actionType":"POSITION_CLOSE_ID","positionId":str(ticket)})
    if int(result.get("numericCode",0))!=10009: raise HTTPException(502,{"message":"MetaApi did not confirm close","result":result})
    return {"ok":True,"account_mode":"DEMO","ticket":ticket,"result":result}

@app.post("/v1/auto/start")
async def auto_start(authorization:Optional[str]=Header(default=None)):
    auth(authorization); await demo_account()
    raise HTTPException(501,"Automatic strategy loop is not implemented in cloud bridge yet; manual DEMO orders only")

@app.get("/v1/auto/status")
async def auto_status(authorization:Optional[str]=Header(default=None)):
    auth(authorization); await demo_account()
    return {"running":False,"supported":False,"last_action":"NOT_IMPLEMENTED","account_mode":"DEMO"}

@app.post("/v1/auto/stop")
async def auto_stop(authorization:Optional[str]=Header(default=None)):
    auth(authorization)
    return {"running":False,"supported":False,"message":"No cloud auto loop is running"}

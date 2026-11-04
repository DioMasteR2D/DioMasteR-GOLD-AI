"""Vantage/MT5 DEMO-only execution bridge. LIVE and contest accounts are rejected."""
import os, hmac, time
from datetime import datetime, timezone
from typing import Optional
import MetaTrader5 as mt5
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

TOKEN=os.environ.get("DIO_BRIDGE_TOKEN","")
HOST=os.environ.get("DIO_BRIDGE_HOST","127.0.0.1")
PORT=int(os.environ.get("DIO_BRIDGE_PORT","8787"))
EXECUTION_ENABLED=os.environ.get("DIO_MT5_DEMO_EXECUTION_ENABLED","false").lower()=="true"
ALLOWED_SYMBOLS={s.strip() for s in os.environ.get("DIO_MT5_ALLOWED_SYMBOLS","XAUUSD").split(",") if s.strip()}
MAX_VOLUME=float(os.environ.get("DIO_MT5_MAX_VOLUME","0.10"))
MAGIC=int(os.environ.get("DIO_MT5_MAGIC","26051105"))
app=FastAPI(title="DioMasteR GOLD AI MT5 DEMO Bridge",version="0.2.0")

class OrderRequest(BaseModel):
    symbol:str=Field(min_length=3,max_length=24)
    side:str
    volume:float=Field(gt=0,le=MAX_VOLUME)
    stop_loss:float=Field(gt=0)
    take_profit:float=Field(gt=0)
    client_order_id:str=Field(min_length=8,max_length=64)

def authorized(value:Optional[str]):
    if not TOKEN: raise HTTPException(503,"Bridge token is not configured")
    supplied=(value or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied,TOKEN): raise HTTPException(401,"Unauthorized")

def connect_demo():
    if not mt5.initialize(): raise HTTPException(503,f"MT5 initialize failed: {mt5.last_error()}")
    terminal,account=mt5.terminal_info(),mt5.account_info()
    if terminal is None or account is None: raise HTTPException(503,"MT5 terminal/account unavailable")
    # MetaTrader5 ACCOUNT_TRADE_MODE_DEMO = 0. Reject LIVE (2) and contest (1).
    if int(account.trade_mode)!=0: raise HTTPException(403,"LIVE/CONTEST account rejected; DEMO account required")
    if not terminal.connected: raise HTTPException(503,"MT5 terminal is not connected to broker")
    if not terminal.trade_allowed: raise HTTPException(403,"MT5 terminal trading is disabled")
    return terminal,account

def symbol_tick(symbol):
    info=mt5.symbol_info(symbol)
    if info is None: raise HTTPException(404,f"Broker symbol not found: {symbol}")
    if not info.visible and not mt5.symbol_select(symbol,True): raise HTTPException(503,"Could not enable broker symbol")
    tick=mt5.symbol_info_tick(symbol)
    if tick is None or tick.bid<=0 or tick.ask<=0: raise HTTPException(503,"Broker quote unavailable")
    return info,tick

@app.get("/health")
def health():
    return {"ok":True,"service":"diomaster-mt5-demo-bridge","execution_enabled":EXECUTION_ENABLED}

@app.get("/v1/status")
def status(authorization:Optional[str]=Header(default=None)):
    authorized(authorization); terminal,account=connect_demo()
    return {"service":"DioMasteR GOLD AI","bridge_version":"0.2.0","terminal_connected":bool(terminal.connected),
      "account_mode":"DEMO","account_login":str(account.login),"server":str(account.server),
      "currency":str(account.currency),"balance":float(account.balance),"equity":float(account.equity),
      "execution_enabled":EXECUTION_ENABLED,"allowed_symbols":sorted(ALLOWED_SYMBOLS),
      "checked_at":datetime.now(timezone.utc).isoformat()}

@app.get("/v1/quote/{symbol}")
def quote(symbol:str,authorization:Optional[str]=Header(default=None)):
    authorized(authorization); connect_demo()
    if symbol not in ALLOWED_SYMBOLS: raise HTTPException(403,"Symbol is not allow-listed")
    _,tick=symbol_tick(symbol)
    return {"symbol":symbol,"bid":float(tick.bid),"ask":float(tick.ask),"time_msc":int(tick.time_msc),"account_mode":"DEMO","contract_size":float(mt5.symbol_info(symbol).trade_contract_size),"volume_min":float(mt5.symbol_info(symbol).volume_min),"volume_step":float(mt5.symbol_info(symbol).volume_step),"volume_max":float(mt5.symbol_info(symbol).volume_max)}

@app.get("/v1/positions")
def positions(authorization:Optional[str]=Header(default=None)):
    authorized(authorization); connect_demo(); rows=mt5.positions_get()
    if rows is None: raise HTTPException(503,f"Positions unavailable: {mt5.last_error()}")
    return {"account_mode":"DEMO","positions":[{"ticket":int(p.ticket),"symbol":p.symbol,"type":int(p.type),
      "volume":float(p.volume),"price_open":float(p.price_open),"price_current":float(p.price_current),
      "profit":float(p.profit),"sl":float(p.sl),"tp":float(p.tp),"magic":int(p.magic)} for p in rows]}

@app.post("/v1/order")
def place_demo_order(req:OrderRequest,authorization:Optional[str]=Header(default=None)):
    authorized(authorization); connect_demo()
    if not EXECUTION_ENABLED: raise HTTPException(423,"DEMO execution is disabled in bridge configuration")
    if req.symbol not in ALLOWED_SYMBOLS: raise HTTPException(403,"Symbol is not allow-listed")
    side=req.side.upper()
    if side not in ("BUY","SELL"): raise HTTPException(422,"side must be BUY or SELL")
    info,tick=symbol_tick(req.symbol)
    if req.volume>MAX_VOLUME: raise HTTPException(422,"Volume exceeds configured maximum")
    step=float(info.volume_step or 0.01); minimum=float(info.volume_min or step)
    if req.volume<minimum or abs(round(req.volume/step)*step-req.volume)>1e-8:
        raise HTTPException(422,f"Volume must respect broker min/step ({minimum}/{step})")
    price=float(tick.ask if side=="BUY" else tick.bid)
    sl,tp=float(req.stop_loss),float(req.take_profit)
    account=mt5.account_info()
    contract_size=float(info.trade_contract_size or 0.0)
    if account is None or contract_size<=0: raise HTTPException(503,"Account equity or contract specification unavailable")
    exposure_oz=float(req.volume)*contract_size
    estimated_risk=abs(price-sl)*exposure_oz
    if exposure_oz>5.0+1e-8: raise HTTPException(422,"Hard exposure limit is 5 troy ounces")
    if estimated_risk>float(account.equity)*0.005+1e-8: raise HTTPException(422,"Order exceeds 0.5% account-equity risk limit")
    point=float(info.point or 0.0); min_gap=float(info.trade_stops_level or 0)*point
    if side=="BUY" and not (sl<price-min_gap and tp>price+min_gap):
        raise HTTPException(422,"BUY requires valid server-side SL below and TP above market")
    if side=="SELL" and not (sl>price+min_gap and tp<price-min_gap):
        raise HTTPException(422,"SELL requires valid server-side SL above and TP below market")
    # Broker-supported fill policy; never retry blindly to avoid duplicate orders.
    filling=int(info.filling_mode)
    fill=mt5.ORDER_FILLING_IOC if filling & 2 else (mt5.ORDER_FILLING_FOK if filling & 1 else mt5.ORDER_FILLING_RETURN)
    request={"action":mt5.TRADE_ACTION_DEAL,"symbol":req.symbol,"volume":float(req.volume),
      "type":mt5.ORDER_TYPE_BUY if side=="BUY" else mt5.ORDER_TYPE_SELL,"price":price,
      "sl":sl,"tp":tp,"deviation":20,"magic":MAGIC,"comment":"DioMasteR DEMO "+req.client_order_id[-12:],
      "type_time":mt5.ORDER_TIME_GTC,"type_filling":fill}
    check=mt5.order_check(request)
    if check is None: raise HTTPException(503,f"Broker order_check failed: {mt5.last_error()}")
    if int(check.retcode)!=0: raise HTTPException(422,{"message":"Broker rejected order check","retcode":int(check.retcode),"comment":str(check.comment)})
    result=mt5.order_send(request)
    if result is None: raise HTTPException(503,f"Broker order_send failed: {mt5.last_error()}")
    if int(result.retcode) not in (mt5.TRADE_RETCODE_DONE,mt5.TRADE_RETCODE_PLACED,mt5.TRADE_RETCODE_DONE_PARTIAL):
        raise HTTPException(422,{"message":"Broker rejected DEMO order","retcode":int(result.retcode),"comment":str(result.comment)})
    return {"ok":True,"account_mode":"DEMO","symbol":req.symbol,"side":side,"volume":float(req.volume),
      "order":int(result.order),"deal":int(result.deal),"price":float(result.price),"retcode":int(result.retcode),
      "comment":str(result.comment),"client_order_id":req.client_order_id}

@app.post("/v1/positions/{ticket}/close")
def close_demo_position(ticket:int,authorization:Optional[str]=Header(default=None)):
    authorized(authorization); connect_demo()
    if not EXECUTION_ENABLED: raise HTTPException(423,"DEMO execution is disabled in bridge configuration")
    rows=mt5.positions_get(ticket=ticket)
    if not rows: raise HTTPException(404,"Position ticket not found")
    p=rows[0]
    if int(p.magic)!=MAGIC: raise HTTPException(403,"Only positions opened by DioMasteR GOLD AI can be closed here")
    _,tick=symbol_tick(p.symbol)
    is_buy=int(p.type)==mt5.POSITION_TYPE_BUY
    request={"action":mt5.TRADE_ACTION_DEAL,"symbol":p.symbol,"volume":float(p.volume),
      "type":mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
      "position":int(p.ticket),"price":float(tick.bid if is_buy else tick.ask),
      "deviation":20,"magic":MAGIC,"comment":"DioMasteR DEMO close",
      "type_time":mt5.ORDER_TIME_GTC,"type_filling":mt5.ORDER_FILLING_IOC}
    check=mt5.order_check(request)
    if check is None or int(check.retcode)!=0: raise HTTPException(422,"Broker rejected close check")
    result=mt5.order_send(request)
    if result is None or int(result.retcode) not in (mt5.TRADE_RETCODE_DONE,mt5.TRADE_RETCODE_DONE_PARTIAL):
      raise HTTPException(422,{"message":"Broker rejected close","retcode":int(result.retcode) if result else -1})
    return {"ok":True,"account_mode":"DEMO","ticket":int(p.ticket),"deal":int(result.deal),"price":float(result.price)}

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host=HOST,port=PORT)

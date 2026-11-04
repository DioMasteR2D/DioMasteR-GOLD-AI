"""Read-only DEMO-only MT5 bridge. No order execution endpoint."""
import os, hmac
from datetime import datetime, timezone
from typing import Optional
import MetaTrader5 as mt5
from fastapi import FastAPI, Header, HTTPException
TOKEN=os.environ.get("DIO_BRIDGE_TOKEN","")
HOST=os.environ.get("DIO_BRIDGE_HOST","127.0.0.1")
PORT=int(os.environ.get("DIO_BRIDGE_PORT","8787"))
app=FastAPI(title="DioMasteR GOLD AI MT5 Demo Bridge",version="0.1.0")
def authorized(value: Optional[str]):
    if not TOKEN: raise HTTPException(503,"Bridge token is not configured")
    supplied=(value or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied,TOKEN): raise HTTPException(401,"Unauthorized")
def snapshot():
    if not mt5.initialize(): raise HTTPException(503, f"MT5 initialize failed: {mt5.last_error()}")
    terminal,account=mt5.terminal_info(),mt5.account_info()
    if terminal is None or account is None: raise HTTPException(503,"MT5 account unavailable")
    # ACCOUNT_TRADE_MODE_DEMO == 0; reject contest and real accounts.
    if int(account.trade_mode)!=0: raise HTTPException(403,"LIVE/CONTEST account rejected; DEMO required")
    return terminal,account
@app.get("/health")
def health(): return {"ok":True,"service":"diomaster-mt5-demo-bridge","execution_enabled":False}
@app.get("/v1/status")
def status(authorization: Optional[str]=Header(default=None)):
    authorized(authorization); terminal,account=snapshot()
    return {"service":"DioMasteR GOLD AI","bridge_version":"0.1.0","terminal_connected":bool(terminal.connected),"account_mode":"DEMO","account_login":str(account.login),"server":str(account.server),"currency":str(account.currency),"balance":float(account.balance),"equity":float(account.equity),"checked_at":datetime.now(timezone.utc).isoformat(),"execution_enabled":False}
@app.get("/v1/quote/{symbol}")
def quote(symbol:str,authorization:Optional[str]=Header(default=None)):
    authorized(authorization); snapshot(); tick=mt5.symbol_info_tick(symbol)
    if tick is None: raise HTTPException(404,f"No tick for {symbol}; check broker symbol")
    return {"symbol":symbol,"bid":float(tick.bid),"ask":float(tick.ask),"time_msc":int(tick.time_msc),"account_mode":"DEMO"}
@app.get("/v1/positions")
def positions(authorization:Optional[str]=Header(default=None)):
    authorized(authorization); snapshot(); rows=mt5.positions_get()
    if rows is None: raise HTTPException(503,f"Positions unavailable: {mt5.last_error()}")
    return {"account_mode":"DEMO","positions":[{"ticket":int(p.ticket),"symbol":p.symbol,"type":int(p.type),"volume":float(p.volume),"price_open":float(p.price_open),"price_current":float(p.price_current),"profit":float(p.profit),"sl":float(p.sl),"tp":float(p.tp)} for p in rows]}
if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host=HOST,port=PORT)

"""DioMasteR GOLD AI bridge for TickerAll MT5 DEMO."""
import os, hmac, uuid, logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

logger=logging.getLogger("diomaster.tickerall.stream")

TA_TOKEN=os.getenv("TICKERALL_API_KEY","").strip()
TA_BASE=os.getenv("TICKERALL_API_BASE","https://api.tickerall.com").rstrip("/")
ACCOUNT_ID=os.getenv("TICKERALL_ACCOUNT_ID","").strip()
BROKER_SERVER=os.getenv("TICKERALL_SERVER","VantageMarkets-Demo").strip()
BROKER_LOGIN=os.getenv("TICKERALL_BROKER_LOGIN","").strip()
BROKER_PASSWORD=os.getenv("TICKERALL_BROKER_PASSWORD","")
SESSION_ACCOUNT_ID=""
SESSION_RECONNECT_LOCK=None
SESSION_LAST_RECONNECT_AT=0.0
BRIDGE_TOKEN=os.getenv("DIO_BRIDGE_TOKEN","")
EXECUTION_ENABLED=os.getenv("DIO_MT5_DEMO_EXECUTION_ENABLED","false").lower()=="true"
SYMBOLS={x.strip() for x in os.getenv("DIO_MT5_ALLOWED_SYMBOLS","XAUUSD").split(",") if x.strip()}
MAX_VOLUME=float(os.getenv("DIO_MT5_MAX_VOLUME","0.01"))
MAX_RISK_FRACTION=float(os.getenv("DIO_MT5_MAX_RISK_FRACTION","0.0025"))
MAX_BOT_POSITIONS=2  # Exactly two concurrent AUTO positions; MANUAL orders are excluded.
app=FastAPI(title="DioMasteR GOLD AI TickerAll DEMO Bridge",version="2.2.0")

# Live bid/ask cache populated by TickerAll's realtime WebSocket.
import asyncio, json, time
import websockets

LIVE_TICKS={}
LIVE_M1_BARS={}
LIVE_M1_CURRENT={}

def record_live_m1_tick(symbol, stamp, bid, ask):
    """Build genuine M1 OHLC bars from broker ticks; never synthesize prices."""
    minute=int(stamp)//60*60
    price=(float(bid)+float(ask))/2.0
    current=LIVE_M1_CURRENT.get(symbol)
    if current is None or current["timestamp"] != minute:
        if current is not None:
            bars=LIVE_M1_BARS.setdefault(symbol, [])
            bars.append(current)
            del bars[:-300]
        current={"timestamp":float(minute),"open":price,"high":price,
                 "low":price,"close":price,"tick_volume":1.0,"spread":float(ask)-float(bid)}
        LIVE_M1_CURRENT[symbol]=current
    else:
        current["high"]=max(current["high"],price)
        current["low"]=min(current["low"],price)
        current["close"]=price
        current["tick_volume"]+=1.0
        current["spread"]=float(ask)-float(bid)

def live_m1_candles(symbol, limit=120):
    rows=list(LIVE_M1_BARS.get(symbol, []))
    current=LIVE_M1_CURRENT.get(symbol)
    if current is not None:
        rows.append(dict(current))
    return rows[-limit:]

def aggregate_live_m1_candles(symbol, timeframe, limit=120):
    """Aggregate only complete, contiguous, closed tick-built M1 bars."""
    minutes={"M5":5,"M15":15,"M30":30,"H1":60}.get(timeframe)
    if not minutes:
        return []
    rows=list(LIVE_M1_BARS.get(symbol, []))  # excludes the still-forming M1 bar
    if len(rows)<minutes:
        return []
    grouped={}
    for bar in rows:
        stamp=int(float(bar.get("timestamp",0)))
        bucket=(stamp//(minutes*60))*(minutes*60)
        grouped.setdefault(bucket,[]).append(bar)
    result=[]
    for bucket in sorted(grouped):
        group=sorted(grouped[bucket],key=lambda x:float(x.get("timestamp",0)))
        stamps=[int(float(x.get("timestamp",0))) for x in group]
        expected=[bucket+i*60 for i in range(minutes)]
        if stamps!=expected:
            continue
        result.append({
            "timestamp":float(bucket),
            "open":float(group[0]["open"]),
            "high":max(float(x["high"]) for x in group),
            "low":min(float(x["low"]) for x in group),
            "close":float(group[-1]["close"]),
            "tick_volume":sum(float(x.get("tick_volume",0)) for x in group),
            "spread":max(float(x.get("spread",0)) for x in group),
        })
    return result[-limit:]

_stream_task=None
STREAM_DIAGNOSTIC={"state":"starting","last_error":None,"last_message_type":None,"symbol":None,"connected_at":None,"last_tick_at":None}

async def live_tick_stream():
    # Reconnect indefinitely with bounded exponential backoff. A clean server
    # close must also retry (the old async-for path could reconnect too fast).
    retry_delay = 3
    max_retry_delay = 20
    while True:
        connected = False
        symbol = None
        try:
            STREAM_DIAGNOSTIC["state"]="checking_demo_account"
            row,_=await account_detail()
            symbols_data=await ta("GET",f"/v1/accounts/{row['id']}/symbols")
            symbols=symbols_data.get("symbols",[])
            symbol=choose_symbol(symbols)
            STREAM_DIAGNOSTIC.update({"state":"connecting","symbol":symbol,"last_error":None})
            logger.info("TickerAll stream: connecting for verified DEMO account; symbol=%s",symbol)
            url="wss://api.tickerall.com/v1/stream?token="+TA_TOKEN
            async with websockets.connect(
                url,
                ping_interval=10,
                ping_timeout=30,
                close_timeout=5,
                open_timeout=15,
                max_queue=256
            ) as ws:
                connected = True
                STREAM_DIAGNOSTIC.update({"state":"connected_subscribing","connected_at":time.time()})
                logger.info("TickerAll WebSocket connected; sending tick subscription for %s",symbol)
                await ws.send(json.dumps({"type":"subscribe","channels":[
                    {"kind":"ticks","accountId":row["id"],"symbols":[symbol]}]}))
                async for raw in ws:
                    msg=json.loads(raw)
                    msg_type=str(msg.get("type") or msg.get("event") or "unknown")
                    STREAM_DIAGNOSTIC["last_message_type"]=msg_type
                    if msg_type!="tick":
                        logger.info("TickerAll WebSocket message received; type=%s keys=%s",msg_type,sorted(msg.keys())[:20])
                    if msg_type=="tick" and msg.get("symbol")==symbol:
                        bid=float(msg.get("bid") or 0); ask=float(msg.get("ask") or 0)
                        stamp=msg.get("timestamp")
                        if isinstance(stamp,str):
                            ts=datetime.fromisoformat(stamp.replace("Z","+00:00")).timestamp()
                        else: ts=float(stamp or 0)
                        if bid>0 and ask>=bid and ts>0:
                            now=time.time()
                            LIVE_TICKS[symbol]={"symbol":symbol,"bid":bid,"ask":ask,
                              "time":ts,"received_at":now,"quote_source":"tickerall_live_websocket_tick",
                              "stale":bool(msg.get("stale",False)),"account_mode":"DEMO"}
                            record_live_m1_tick(symbol,ts,bid,ask)
                            STREAM_DIAGNOSTIC.update({"state":"receiving_ticks","last_tick_at":now,"last_error":None})
                            retry_delay = 3
                        else:
                            logger.warning("TickerAll tick rejected: invalid bid/ask/timestamp; symbol=%s",symbol)
            # The server may close cleanly without raising. Treat that as a
            # disconnect, invalidate the cached quote and reconnect slowly.
            raise ConnectionError("TickerAll WebSocket closed the stream")
        except asyncio.CancelledError:
            STREAM_DIAGNOSTIC["state"]="stopped"
            raise
        except HTTPException as exc:
            if symbol:
                LIVE_TICKS.pop(symbol, None)
            recovery_error = None
            if exc.status_code == 409:
                try:
                    await create_demo_session("TickerAll WebSocket rejected account with HTTP 409")
                except Exception as recovery_exc:
                    recovery_error = str(recovery_exc)[:200]
            message = "HTTPException " + str(exc.status_code) + ": " + str(exc.detail)[:220]
            if recovery_error:
                message += " | recovery: " + recovery_error
            STREAM_DIAGNOSTIC.update({"state":"error_retrying","last_error":message})
            logger.warning("TickerAll live stream disconnected; connected=%s retry_in=%ss error=%s",
                           connected, retry_delay, message)
            await asyncio.sleep(retry_delay)
            retry_delay = min(max_retry_delay, retry_delay * 2)
        except Exception as exc:
            if symbol:
                LIVE_TICKS.pop(symbol, None)
            STREAM_DIAGNOSTIC.update({"state":"error_retrying","last_error":f"{type(exc).__name__}: {str(exc)[:300]}"})
            logger.warning("TickerAll live stream disconnected; connected=%s retry_in=%ss error=%s",
                           connected, retry_delay, f"{type(exc).__name__}: {str(exc)[:200]}")
            await asyncio.sleep(retry_delay)
            retry_delay = min(max_retry_delay, retry_delay * 2)

@app.on_event("startup")
async def start_live_stream():
    global _stream_task
    _stream_task=asyncio.create_task(live_tick_stream())

@app.on_event("shutdown")
async def stop_live_stream():
    if _stream_task:
        _stream_task.cancel()

class Order(BaseModel):
    symbol:str=Field(min_length=3,max_length=32)
    side:str
    volume:float=Field(gt=0,le=MAX_VOLUME)
    stop_loss:float=Field(gt=0)
    take_profit:float=Field(gt=0)
    client_order_id:str=Field(min_length=8,max_length=64)
    order_origin:str="AUTO"

def auth(value:Optional[str]):
    if not BRIDGE_TOKEN: raise HTTPException(503,"DIO_BRIDGE_TOKEN is not configured")
    got=(value or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got.encode("utf-8"),BRIDGE_TOKEN.encode("utf-8")): raise HTTPException(401,"Unauthorized")

def configured():
    if not TA_TOKEN: raise HTTPException(503,"TickerAll API key is not configured")
    if not BRIDGE_TOKEN: raise HTTPException(503,"Bridge auth is not configured")

async def ta(method,path,body=None,idem=False):
    configured()
    headers={"Authorization":"Bearer "+TA_TOKEN,"Accept":"application/json"}
    if body is not None: headers["Content-Type"]="application/json"
    if idem: headers["Idempotency-Key"]=str(uuid.uuid4())
    # Retry only idempotent GETs on transient gateway/rate-limit responses.
    # Never retry order/session POSTs automatically.
    attempts=3 if method.upper()=="GET" else 1
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0)) as client:
        for attempt in range(attempts):
            try:
                r=await client.request(method,TA_BASE+path,headers=headers,json=body)
            except (httpx.TimeoutException,httpx.NetworkError):
                if method.upper()!="GET" or attempt+1>=attempts:
                    raise
                await asyncio.sleep(0.4*(attempt+1))
                continue
            if r.status_code in (502,503,504,429) and method.upper()=="GET" and attempt+1<attempts:
                await asyncio.sleep(0.4*(attempt+1))
                continue
            break
    if r.status_code>=400:
        try:
            data=r.json(); detail=data.get("message") or data.get("error") or str(data)
        except Exception: detail=r.text[:400]
        raise HTTPException(r.status_code,str(detail)[:500])
    if not r.content: return {}
    return r.json()

async def create_demo_session(reason):
    global SESSION_ACCOUNT_ID, SESSION_LAST_RECONNECT_AT, SESSION_RECONNECT_LOCK
    if not BROKER_LOGIN or not BROKER_PASSWORD:
        raise HTTPException(503,
            "Vantage DEMO auto-reconnect unavailable: set TICKERALL_BROKER_LOGIN and TICKERALL_BROKER_PASSWORD in Render Environment.")
    if SESSION_RECONNECT_LOCK is None:
        SESSION_RECONNECT_LOCK=asyncio.Lock()
    async with SESSION_RECONNECT_LOCK:
        # Avoid creating duplicate sessions when status, quote and stream calls
        # all detect the same outage at nearly the same time.
        if SESSION_ACCOUNT_ID and time.time()-SESSION_LAST_RECONNECT_AT < 30:
            try:
                current=await ta("GET",f"/v1/accounts/{SESSION_ACCOUNT_ID}")
                if (current.get("isDemo") is True and
                    str(current.get("status","")).lower() in ("online","connected")):
                    return current
            except Exception:
                pass
            raise HTTPException(503,"Vantage DEMO reconnect is cooling down; retrying shortly.")
        logger.warning("TickerAll DEMO session recovery started; reason=%s",str(reason)[:160])
        session=await ta("POST","/v1/sessions",{
            "broker":"mt5","server":BROKER_SERVER,
            "account":BROKER_LOGIN,"password":BROKER_PASSWORD
        })
        payload=session if isinstance(session,dict) else {}
        nested=payload.get("session") if isinstance(payload.get("session"),dict) else {}
        data=payload.get("data") if isinstance(payload.get("data"),dict) else {}
        account_id=(payload.get("accountId") or nested.get("accountId") or data.get("accountId") or "")
        if not account_id:
            logger.error("TickerAll recovery session missing accountId; response_keys=%s",
                         sorted(payload.keys()))
            raise HTTPException(502,"TickerAll recovery did not return accountId")
        detail=await ta("GET",f"/v1/accounts/{account_id}")
        if str(detail.get("id"))!=str(account_id):
            raise HTTPException(502,"TickerAll recovery account detail mismatch")
        if detail.get("isDemo") is not True:
            raise HTTPException(403,"Recovered TickerAll account is not verified DEMO; trading blocked")
        if str(detail.get("broker","")).lower()!="mt5":
            raise HTTPException(403,"Recovered account is not MT5")
        if str(detail.get("server","")).lower()!=BROKER_SERVER.lower():
            raise HTTPException(403,"Recovered account server does not match configured Vantage DEMO server")
        account_number=str(detail.get("accountNumber","")).replace("*","")
        if BROKER_LOGIN and account_number and not account_number.endswith(BROKER_LOGIN[-4:]):
            raise HTTPException(403,"Recovered Vantage DEMO login does not match configured login")
        SESSION_ACCOUNT_ID=str(account_id)
        SESSION_LAST_RECONNECT_AT=time.time()
        logger.info("TickerAll Vantage MT5 DEMO session recovered and verified; account id withheld")
        if str(detail.get("status","")).lower() not in ("online","connected"):
            raise HTTPException(503,"TickerAll created a DEMO session but broker status is not online yet")
        return detail

async def account():
    global SESSION_ACCOUNT_ID
    # Prefer the most recently verified session over a stale configured ID.
    known_id=SESSION_ACCOUNT_ID or ACCOUNT_ID
    match=None
    if known_id:
        try:
            match=await ta("GET",f"/v1/accounts/{known_id}")
        except HTTPException as exc:
            # A 409 explicitly means the broker account is no longer connected.
            # Re-authenticate only with the configured credentials, then verify
            # DEMO, MT5, server and login before accepting the new account id.
            if exc.status_code!=409:
                if ACCOUNT_ID or exc.status_code!=404:
                    raise
                SESSION_ACCOUNT_ID=""
            else:
                match=await create_demo_session(f"account lookup returned HTTP {exc.status_code}")
    if not match:
        match=await create_demo_session("no active TickerAll session")
    if match.get("isDemo") is not True:
        raise HTTPException(403,"TickerAll did not verify this as DEMO")
    if str(match.get("broker","")).lower()!="mt5":
        raise HTTPException(403,"Only MT5 is allowed")
    if str(match.get("server","")).lower()!=BROKER_SERVER.lower():
        raise HTTPException(403,"Unexpected broker server")
    account_number=str(match.get("accountNumber","")).replace("*","")
    if BROKER_LOGIN and account_number and not account_number.endswith(BROKER_LOGIN[-4:]):
        raise HTTPException(403,"Connected Vantage DEMO login does not match configured login")
    SESSION_ACCOUNT_ID=str(match.get("id") or SESSION_ACCOUNT_ID)
    return match

async def account_detail():
    row=await account()
    detail=await ta("GET",f"/v1/accounts/{row['id']}")
    if detail.get("isDemo") is not True:
        raise HTTPException(403,"DEMO verification failed; trading blocked")
    if str(detail.get("status","")).lower() not in ("online","connected"):
        detail=await create_demo_session("account status offline/cold")
        row=detail
    if str(detail.get("status","")).lower() not in ("online","connected"):
        raise HTTPException(503,"Vantage DEMO connection is still offline; new entries blocked")
    return row,detail

def choose_symbol(symbols):
    available=symbols or []
    for preferred in ("XAUUSD","XAUUSDm","GOLD","GOLDm"):
        if preferred in available: return preferred
    for s in available:
        if "XAUUSD" in str(s).upper() or str(s).upper().startswith("GOLD"): return str(s)
    return next(iter(SYMBOLS), "XAUUSD")

@app.get("/")
@app.head("/")
def root_health():
    return {"ok":True,"service":"diomaster-tickerall-demo-bridge","health":"/health","bridge_version":"2.3.0"}

@app.get("/health")
def health():
    return {"ok":True,"service":"diomaster-tickerall-demo-bridge","bridge_version":"2.3.0"}

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
      "always_hot":bool(row.get("alwaysHot",False)),
      "price_stream_state":STREAM_DIAGNOSTIC.get("state"),
      "price_stream_last_error":STREAM_DIAGNOSTIC.get("last_error"),
      "price_stream_symbol":STREAM_DIAGNOSTIC.get("symbol"),
      "price_stream_last_tick_at":STREAM_DIAGNOSTIC.get("last_tick_at")}

@app.get("/v1/quote/{symbol}")
async def quote(symbol:str,authorization:Optional[str]=Header(default=None)):
    auth(authorization); row,_=await account_detail()
    symbols_data=await ta("GET",f"/v1/accounts/{row['id']}/symbols")
    if symbol not in symbols_data.get("symbols",[]):
        raise HTTPException(404,"Broker-native symbol not found; inspect /v1/status allowed_symbols")
    tick=LIVE_TICKS.get(symbol)
    if not tick:
        raise HTTPException(503,"WAITING_FOR_LIVE_TICK: TickerAll WebSocket has not delivered a live broker tick yet")
    age=time.time()-float(tick["received_at"])
    if tick.get("stale") or age>15:
        raise HTTPException(503,f"STALE_LIVE_TICK: last broker tick is {int(age)} seconds old")
    return {k:v for k,v in tick.items() if k!="received_at"}

# Per-symbol/timeframe candle cache. Serve cached OHLC immediately and refresh
# in the background so switching timeframes does not block the Android UI.
CANDLE_CACHE={}
CANDLE_REFRESH_TASKS={}
CANDLE_CACHE_TTL={"M1":15,"M5":20,"M15":30,"M30":45,"H1":60,"H4":90,"D1":120,"W1":180,"MN1":300}

async def refresh_candle_cache(key, account_id, symbol, timeframe, hours):
    try:
        data=await ta("GET",f"/v1/accounts/{account_id}/candles?symbol={symbol}&timeframe={timeframe}&hours={hours}")
        rows=data.get("candles",[])
        if not isinstance(rows,list):
            raise ValueError("TickerAll candle payload is invalid")
        clean=[]
        invalid_rows=0
        first_keys=sorted(rows[0].keys()) if rows and isinstance(rows[0],dict) else []
        first_types={k:type(v).__name__ for k,v in rows[0].items()} if rows and isinstance(rows[0],dict) else {}
        for bar in rows:
            try:
                clean.append({"timestamp":float(bar["timestamp"]),"open":float(bar["open"]),
                  "high":float(bar["high"]),"low":float(bar["low"]),"close":float(bar["close"]),
                  "tick_volume":float(bar.get("tickVolume") or 0),"spread":float(bar.get("spread") or 0)})
            except (KeyError,TypeError,ValueError):
                invalid_rows+=1
        diagnostic = ("TickerAll candles diagnostic: symbol=%s timeframe=%s hours=%s raw_count=%s valid_count=%s invalid_count=%s first_keys=%s first_types=%s coverage=%s truncated=%s served=%s stop_reason=%s note=%s response_keys=%s" %
          (symbol,timeframe,hours,len(rows),len(clean),invalid_rows,first_keys,first_types,
           data.get("coverage"),bool(data.get("truncated",False)),data.get("served"),
           data.get("stopReason"),str(data.get("note") or "")[:180],sorted(data.keys())))
        print(diagnostic,flush=True)
        logger.info(diagnostic)
        # Keep only valid real broker OHLC. Empty/partial failures never erase a
        # previously good cache.
        if len(clean)>=2:
            CANDLE_CACHE[key]={"candles":clean,"fetched_at":time.time(),
              "coverage":data.get("coverage"),"truncated":bool(data.get("truncated",False)),
              "served":data.get("served")}
        elif key not in CANDLE_CACHE:
            CANDLE_CACHE[key]={"candles":clean,"fetched_at":time.time(),
              "coverage":data.get("coverage"),"truncated":bool(data.get("truncated",False)),
              "served":data.get("served")}
    except Exception as exc:
        logger.warning("TickerAll candle refresh failed: symbol=%s timeframe=%s error=%s",
                       symbol,timeframe,str(exc)[:200])
    finally:
        CANDLE_REFRESH_TASKS.pop(key,None)

@app.get("/v1/candles/{symbol}")
async def candles(symbol:str,timeframe:str="M15",hours:int=24,authorization:Optional[str]=Header(default=None)):
    auth(authorization); row,_=await account_detail()
    allowed_frames={"M1","M5","M15","M30","H1","H4","D1","W1","MN1"}
    if timeframe not in allowed_frames: raise HTTPException(422,"Unsupported timeframe")
    if hours<1 or hours>8760: raise HTTPException(422,"hours must be between 1 and 8760")
    symbols_data=await ta("GET",f"/v1/accounts/{row['id']}/symbols")
    if symbol not in symbols_data.get("symbols",[]): raise HTTPException(404,"Broker-native symbol not found")

    key=(symbol,timeframe,hours)
    cached=CANDLE_CACHE.get(key)
    age=(time.time()-cached["fetched_at"]) if cached else None
    ttl=CANDLE_CACHE_TTL.get(timeframe,60)
    task=CANDLE_REFRESH_TASKS.get(key)
    if task is None and (cached is None or age>=ttl):
        task=asyncio.create_task(refresh_candle_cache(key,row["id"],symbol,timeframe,hours))
        CANDLE_REFRESH_TASKS[key]=task

    # First load waits briefly for genuine TickerAll OHLC. Later timeframe
    # switches return cached bars immediately while a refresh runs.
    if cached is None and task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(task),timeout=10)
        except asyncio.TimeoutError:
            pass
        cached=CANDLE_CACHE.get(key)

    clean=list(cached.get("candles",[])) if cached else []
    effective_timeframe=timeframe
    source="tickerall_history_cache" if cached else "tickerall_history_pending"
    fallback_reason=None
    # When TickerAll historical candles are unavailable, aggregate only
    # complete contiguous closed M1 bars built from genuine broker ticks.
    if len(clean)<2:
        aggregated=aggregate_live_m1_candles(symbol,timeframe,120)
        if len(aggregated)>=2:
            clean=aggregated
            source="tickerall_live_ticks_aggregated"
        else:
            live_rows=live_m1_candles(symbol,120)
            if timeframe=="M1" and len(live_rows)>=2:
                clean=live_rows
                effective_timeframe="M1"
                source="tickerall_live_ticks"
            elif len(live_rows)<2:
                fallback_reason="WAITING_FOR_SUFFICIENT_LIVE_TICKS"
            else:
                fallback_reason="WAITING_FOR_COMPLETE_CONTIGUOUS_M1_BARS"
    return {"account_mode":"DEMO","symbol":symbol,"timeframe":effective_timeframe,
      "requested_timeframe":timeframe,"effective_timeframe":effective_timeframe,
      "source":source,"fallback_reason":fallback_reason,
      "candles":clean,"count":len(clean),
      "coverage":cached.get("coverage") if cached else None,
      "truncated":cached.get("truncated",False) if cached else False,
      "served":cached.get("served") if cached else None,
      "cache_age_seconds":round(age,1) if age is not None else None,
      "refreshing":key in CANDLE_REFRESH_TASKS}

@app.get("/v1/history")
async def history(symbol:Optional[str]=None,limit:int=50,authorization:Optional[str]=Header(default=None)):
    auth(authorization); row,_=await account_detail()
    limit=max(1,min(limit,200))
    query=f"?limit={limit}"
    if symbol: query+=f"&symbol={symbol}"
    data=await ta("GET",f"/v1/accounts/{row['id']}/history{query}")
    rows=data.get("history",data.get("trades",[])) if isinstance(data,dict) else data
    if not isinstance(rows,list): raise HTTPException(502,"TickerAll history payload is invalid")
    return {"account_mode":"DEMO","history":rows,"count":len(rows)}

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
    origin=str(req.order_origin or "AUTO").upper()
    if origin not in ("AUTO","MANUAL"):
        raise HTTPException(422,"order_origin must be AUTO or MANUAL")
    # Manual user orders must not consume the AI bot's own position quota.
    # Legacy DioMasteR-tagged positions remain counted conservatively.
    if origin=="AUTO":
        bot=[p for p in open_rows if str(p.get("comment","")).startswith("DioMasteR")
             and not str(p.get("comment","")).startswith("DioMasteR MANUAL")]
        if len(bot)>=MAX_BOT_POSITIONS:
            raise HTTPException(423,f"Maximum of {MAX_BOT_POSITIONS} bot positions reached")
    body={"type":"market","symbol":req.symbol,"side":side,"volume":req.volume,
      "stopLoss":sl,"takeProfit":tp,
      "comment":"DioMasteR MANUAL "+req.client_order_id[-16:] if origin=="MANUAL"
                else "DioMasteR AUTO "+req.client_order_id[-16:]}
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


@app.get("/assistant/snapshot")
async def assistant_snapshot(limit:int=50,authorization:Optional[str]=Header(default=None)):
    """Read-only consolidated snapshot for an external AI assistant. DEMO only."""
    auth(authorization)
    row,detail=await account_detail()
    limit=max(1,min(limit,200))
    account_data=detail.get("account",{}) if isinstance(detail,dict) else {}
    positions_data=await ta("GET",f"/v1/accounts/{row['id']}/positions")
    history_data=await ta("GET",f"/v1/accounts/{row['id']}/history?limit={limit}")
    open_rows=positions_data.get("positions",[]) if isinstance(positions_data,dict) else []
    history_rows=history_data.get("history",history_data.get("trades",[])) if isinstance(history_data,dict) else history_data
    if not isinstance(open_rows,list) or not isinstance(history_rows,list):
        raise HTTPException(502,"TickerAll assistant snapshot payload is invalid")
    safe_positions=[]
    for p in open_rows:
        safe_positions.append({
            "ticket":int(p.get("ticket") or 0),
            "symbol":p.get("symbol"),
            "side":str(p.get("side") or "").upper(),
            "volume":float(p.get("volume") or 0),
            "entry_price":float(p.get("entryPrice") or 0),
            "current_price":float(p.get("currentPrice") or 0),
            "profit":float(p.get("profit") or 0),
            "stop_loss":float(p.get("stopLoss") or 0),
            "take_profit":float(p.get("takeProfit") or 0)
        })
    return {
        "service":"DioMasteR GOLD AI",
        "account_mode":"DEMO",
        "read_only":True,
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "connection":{
            "connected":True,
            "broker":str(row.get("broker") or "MT5"),
            "server":str(row.get("server") or ""),
            "symbol":choose_symbol((await ta("GET",f"/v1/accounts/{row['id']}/symbols")).get("symbols",[])),
            "price_stream_state":STREAM_DIAGNOSTIC.get("state"),
            "last_tick_at":STREAM_DIAGNOSTIC.get("last_tick_at")
        },
        "account":{
            "currency":str(account_data.get("currency") or "USD"),
            "balance":float(account_data.get("balance") or 0),
            "equity":float(account_data.get("equity") or 0),
            "margin":float(account_data.get("margin") or 0),
            "free_margin":float(account_data.get("freeMargin") or 0)
        },
        "open_positions":safe_positions,
        "open_positions_count":len(safe_positions),
        "closed_history":history_rows,
        "closed_history_count":len(history_rows)
    }

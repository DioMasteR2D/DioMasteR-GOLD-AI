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
MAX_BOT_POSITIONS=2  # Two concurrent EMA legs; combined risk remains capped.
app=FastAPI(title="DioMasteR GOLD AI TickerAll DEMO Bridge",version="2.2.0")
from assistant_mcp import router as assistant_mcp_router
app.include_router(assistant_mcp_router)
from assistant_api import router as assistant_api_router
app.include_router(assistant_api_router)

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
    # Keep the TickerAll realtime stream alive, verify subscription acceptance,
    # and reconnect if the socket is connected but stops delivering messages.
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
            account_id=str(row["id"])
            correlation_id="diomaster-"+uuid.uuid4().hex[:12]
            STREAM_DIAGNOSTIC.update({"state":"connecting","symbol":symbol,"last_error":None,
                                      "last_message_type":None})
            logger.info("TickerAll stream: connecting for verified DEMO account; symbol=%s account_id=%s",
                        symbol,account_id)
            url="wss://api.tickerall.com/v1/stream?token="+TA_TOKEN
            async with websockets.connect(
                url, ping_interval=10, ping_timeout=30, close_timeout=5,
                open_timeout=15, max_queue=256
            ) as ws:
                connected = True
                STREAM_DIAGNOSTIC.update({"state":"connected_subscribing","connected_at":time.time()})
                subscribe={"type":"subscribe","channels":[
                    {"kind":"ticks","accountId":account_id,"symbols":[symbol]}],
                    "correlationId":correlation_id}
                await ws.send(json.dumps(subscribe))
                logger.info("TickerAll WebSocket subscription sent; symbol=%s correlation_id=%s",
                            symbol,correlation_id)
                last_rx=time.monotonic()
                last_ping=last_rx
                missed_heartbeats=0
                subscribed=False
                while True:
                    try:
                        raw=await asyncio.wait_for(ws.recv(),timeout=20)
                    except asyncio.TimeoutError:
                        # TickerAll supports an application-level ping/pong in
                        # addition to WebSocket protocol pings.
                        await ws.send(json.dumps({"type":"ping"}))
                        missed_heartbeats+=1
                        logger.warning("TickerAll stream heartbeat sent; symbol=%s missed=%s",
                                       symbol,missed_heartbeats)
                        if missed_heartbeats>=3:
                            raise TimeoutError("TickerAll stream silent for 60 seconds")
                        continue
                    last_rx=time.monotonic()
                    missed_heartbeats=0
                    msg=json.loads(raw)
                    if not isinstance(msg,dict):
                        logger.warning("TickerAll stream ignored non-object frame")
                        continue
                    msg_type=str(msg.get("type") or msg.get("event") or "unknown")
                    STREAM_DIAGNOSTIC["last_message_type"]=msg_type
                    if msg_type=="subscribed":
                        accepted=msg.get("channels",[])
                        rejected=msg.get("rejected",[])
                        if rejected or not any(
                            ch.get("kind")=="ticks" and str(ch.get("accountId"))==account_id
                            and symbol in ch.get("symbols",[]) for ch in accepted if isinstance(ch,dict)
                        ):
                            detail=json.dumps({"accepted":accepted,"rejected":rejected},ensure_ascii=False)[:500]
                            raise RuntimeError("TickerAll tick subscription not accepted: "+detail)
                        subscribed=True
                        STREAM_DIAGNOSTIC.update({"state":"subscribed_waiting_for_tick","last_error":None})
                        logger.info("TickerAll tick subscription accepted; symbol=%s",symbol)
                        continue
                    if msg_type=="error":
                        raise RuntimeError("TickerAll stream error: "+str(msg.get("code"))+" "+str(msg.get("message"))[:250])
                    if msg_type=="ping":
                        await ws.send(json.dumps({"type":"pong"}))
                        continue
                    if msg_type=="pong":
                        last_ping=time.monotonic()
                        STREAM_DIAGNOSTIC.update({"state":"heartbeat_ok"})
                        continue
                    if msg_type!="tick":
                        logger.info("TickerAll WebSocket message received; type=%s keys=%s",
                                    msg_type,sorted(msg.keys())[:20])
                        continue
                    if msg.get("symbol")!=symbol:
                        continue
                    if msg.get("accountId") and str(msg.get("accountId"))!=account_id:
                        logger.warning("TickerAll tick ignored for unexpected account; symbol=%s",symbol)
                        continue
                    bid=float(msg.get("bid") or 0)
                    ask=float(msg.get("ask") or 0)
                    stamp=msg.get("timestamp")
                    if isinstance(stamp,str):
                        ts=datetime.fromisoformat(stamp.replace("Z","+00:00")).timestamp()
                    else:
                        ts=float(stamp or 0)
                    if bid<=0 or ask<bid or ts<=0:
                        logger.warning("TickerAll tick rejected: invalid bid/ask/timestamp; symbol=%s",symbol)
                        continue
                    now=time.time()
                    is_stale=bool(msg.get("stale",False))
                    LIVE_TICKS[symbol]={"symbol":symbol,"bid":bid,"ask":ask,
                      "time":ts,"received_at":now,"quote_source":"tickerall_live_websocket_tick",
                      "stale":is_stale,"account_mode":"DEMO"}
                    if not is_stale:
                        record_live_m1_tick(symbol,ts,bid,ask)
                        STREAM_DIAGNOSTIC.update({"state":"receiving_ticks","last_tick_at":now,"last_error":None})
                        retry_delay=3
                    else:
                        STREAM_DIAGNOSTIC.update({"state":"stale_last_quote","last_error":"TickerAll sent stale last-known quote"})
                    if not subscribed:
                        logger.warning("TickerAll delivered a tick before subscription acknowledgement")
        except asyncio.CancelledError:
            STREAM_DIAGNOSTIC["state"]="stopped"
            raise
        except HTTPException as exc:
            if symbol:
                LIVE_TICKS.pop(symbol,None)
            recovery_error=None
            if exc.status_code==409:
                try:
                    await create_demo_session("TickerAll WebSocket rejected account with HTTP 409")
                except Exception as recovery_exc:
                    recovery_error=str(recovery_exc)[:200]
            message="HTTPException "+str(exc.status_code)+": "+str(exc.detail)[:220]
            if recovery_error:
                message+=" | recovery: "+recovery_error
            STREAM_DIAGNOSTIC.update({"state":"error_retrying","last_error":message})
            logger.warning("TickerAll live stream disconnected; connected=%s retry_in=%ss error=%s",
                           connected,retry_delay,message)
            await asyncio.sleep(retry_delay)
            retry_delay=min(max_retry_delay,retry_delay*2)
        except Exception as exc:
            if symbol:
                LIVE_TICKS.pop(symbol,None)
            message=f"{type(exc).__name__}: {str(exc)[:300]}"
            STREAM_DIAGNOSTIC.update({"state":"error_retrying","last_error":message})
            logger.warning("TickerAll live stream disconnected; connected=%s retry_in=%ss error=%s",
                           connected,retry_delay,message)
            await asyncio.sleep(retry_delay)
            retry_delay=min(max_retry_delay,retry_delay*2)

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

async def ta(method,path,body=None,idem=False,idempotency_key=None):
    configured()
    headers={"Authorization":"Bearer "+TA_TOKEN,"Accept":"application/json"}
    if body is not None: headers["Content-Type"]="application/json"
    if idem: headers["Idempotency-Key"]=str(idempotency_key or uuid.uuid4())
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

def _account_payload(payload):
    current = payload if isinstance(payload, dict) else {}
    for _ in range(3):
        nested = None
        for key in ('account', 'data', 'result'):
            value = current.get(key)
            if isinstance(value, dict) and any(k in value for k in ('id', 'accountId', 'isDemo', 'broker', 'server')):
                nested = value
                break
        if nested is None:
            break
        current = nested
    return current

def _is_demo(value):
    return value is True or (isinstance(value, str) and value.strip().lower() in ('true', 'demo', '1', 'yes'))

def _server_matches(actual):
    norm = lambda x: ''.join(ch for ch in str(x or '').lower() if ch.isalnum())
    return bool(norm(actual) and norm(actual) == norm(BROKER_SERVER))
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
                current=_account_payload(await ta("GET",f"/v1/accounts/{SESSION_ACCOUNT_ID}"))
                if (_is_demo(current.get("isDemo")) and
                    str(current.get("status","")).lower() in ("online","connected")):
                    return current
            except Exception:
                pass
            raise HTTPException(503,"Vantage DEMO reconnect is cooling down; retrying shortly.")
        logger.warning("TickerAll DEMO session recovery started; reason=%s expected_server=%s",str(reason)[:160],BROKER_SERVER)
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
        detail=_account_payload(await ta("GET",f"/v1/accounts/{account_id}"))
        if str(detail.get("id"))!=str(account_id):
            raise HTTPException(502,"TickerAll recovery account detail mismatch")
        if not _is_demo(detail.get("isDemo")):
            raise HTTPException(403,"Recovered TickerAll account is not verified DEMO; trading blocked")
        if str(detail.get("broker","")).lower()!="mt5":
            raise HTTPException(403,"Recovered account is not MT5")
        if not _server_matches(detail.get("server")):
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
            match=_account_payload(await ta("GET",f"/v1/accounts/{known_id}"))
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
    if not _is_demo(match.get("isDemo")):
        raise HTTPException(403,"TickerAll did not verify this as DEMO")
    if str(match.get("broker","")).lower()!="mt5":
        raise HTTPException(403,"Only MT5 is allowed")
    if not _server_matches(match.get("server")):
        raise HTTPException(403,"Vantage DEMO server verification failed")
    account_number=str(match.get("accountNumber","")).replace("*","")
    if BROKER_LOGIN and account_number and not account_number.endswith(BROKER_LOGIN[-4:]):
        raise HTTPException(403,"Connected Vantage DEMO login does not match configured login")
    SESSION_ACCOUNT_ID=str(match.get("id") or SESSION_ACCOUNT_ID)
    return match

async def account_detail():
    row=await account()
    detail=_account_payload(await ta("GET",f"/v1/accounts/{row['id']}"))
    if not _is_demo(detail.get("isDemo")):
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
AUTO_STRATEGY_CACHE={}
AUTO_STRATEGY_CACHE_TTL={"M1":2,"M5":3,"M15":5,"H1":20,"H4":45}
CANDLE_CACHE_TTL={"M1":3,"M5":5,"M15":10,"M30":20,"H1":30,"H4":60,"D1":120,"W1":180,"MN1":300}

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
        bot_symbol_positions=[p for p in open_rows if str(p.get("symbol",""))==req.symbol and str(p.get("comment","")).startswith("DioMasteR AUTO EMA")]
        nonbot_symbol_positions=[p for p in open_rows if str(p.get("symbol",""))==req.symbol and not str(p.get("comment","")).startswith("DioMasteR AUTO EMA")]
        if nonbot_symbol_positions:
            raise HTTPException(423,"AUTO entry blocked: a non-bot position already exists for this symbol")
        if len(bot_symbol_positions)>=MAX_BOT_POSITIONS:
            raise HTTPException(423,"Two-position rule: EMA bot position limit reached")
        if not req.client_order_id.startswith("EMA"): 
            raise HTTPException(422,"AUTO order requires EMA idempotency key")
    leg_tag=(" FAST" if "FAST" in req.client_order_id.upper() else
             " RUNNER" if "RUNNER" in req.client_order_id.upper() else "")
    body={"type":"market","symbol":req.symbol,"side":side,"volume":req.volume,
      "stopLoss":sl,"takeProfit":tp,
      "comment":"DioMasteR MANUAL "+req.client_order_id[-14:] if origin=="MANUAL"
                else "DioMasteR AUTO EMA "+req.client_order_id[-14:]}
    result=await ta("POST",f"/v1/accounts/{row['id']}/orders",body,idem=True,idempotency_key=req.client_order_id)
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

# EMA crossover AUTO strategy. TickerAll, Android endpoints and data stores remain unchanged.
import pandas as pd
from ema_strategy import StrategyConfig, get_signal
AUTO_TASK=None
AUTO_LOCK=asyncio.Lock()
AUTO_TIMEFRAME=StrategyConfig().timeframe
AUTO_TREND_TIMEFRAME=os.getenv("DIO_EMA_TREND_TIMEFRAME","M15").upper()
AUTO_MAX_TRADES_PER_DAY=int(os.getenv("DIO_AUTO_MAX_TRADES_PER_DAY","20"))
AUTO_DAILY_LOSS_LIMIT=float(os.getenv("DIO_AUTO_DAILY_LOSS_LIMIT","0.05"))
AUTO_MAX_CONSECUTIVE_LOSSES=int(os.getenv("DIO_AUTO_MAX_CONSECUTIVE_LOSSES","3"))
AUTO_NEWS_WINDOWS=os.getenv("DIO_AUTO_NEWS_WINDOWS_UTC","").strip()
AUTO_STATE={"running":False,"account_mode":"DEMO","strategy":"EMA_CROSSOVER","last_action":"STOPPED","last_error":None,"last_signal":None,"last_bar_time":None,"trades_today":0,"daily_start_equity":None,"utc_day":None,"consecutive_losses":0,"known_ticket":None,"kill_switch":False,"reconciled":False,"last_order_key":None}
AUTO_CANDLE_SECONDS={"M1":60,"M5":300,"M15":900,"M30":1800,"H1":3600,"H4":14400}
AUTO_FRAME_CACHE={}
AUTO_FRAME_CACHE_TTL=float(os.getenv("DIO_AUTO_CANDLE_CACHE_SECONDS","15"))

def _news_blocked(now=None):
    if not AUTO_NEWS_WINDOWS: return False
    now=now or datetime.now(timezone.utc)
    try:
        current=now.strftime("%H:%M")
        for item in AUTO_NEWS_WINDOWS.split(","):
            a,b=[x.strip() for x in item.split("-",1)]
            if a<=b and a<=current<=b: return True
            if a>b and (current>=a or current<=b): return True
        return False
    except Exception:
        logger.error("Invalid DIO_AUTO_NEWS_WINDOWS_UTC; fail-closed")
        return True

def _bot_positions(rows):
    return [p for p in rows if str(p.get("comment","")).startswith("DioMasteR AUTO EMA")]

async def reconcile_orders(account_id):
    data=await ta("GET",f"/v1/accounts/{account_id}/positions")
    rows=data.get("positions",[]) if isinstance(data,dict) else []
    if not isinstance(rows,list): raise RuntimeError("Invalid broker positions payload")
    bot=_bot_positions(rows)
    if len(bot)>MAX_BOT_POSITIONS: raise HTTPException(423,"Reconciliation failed: EMA bot position limit exceeded")
    for p in bot:
        if float(p.get("stopLoss") or 0)<=0 or float(p.get("takeProfit") or 0)<=0:
            raise HTTPException(423,"Reconciliation failed: position missing server-side SL/TP")
    AUTO_STATE["known_ticket"]=int(bot[0].get("ticket") or 0) if bot else None
    AUTO_STATE["known_tickets"]=[int(p.get("ticket") or 0) for p in bot]
    AUTO_STATE["reconciled"]=True
    AUTO_STATE["broker_bot_positions"]=len(bot)
    return rows

async def _kill_switch(reason):
    AUTO_STATE.update({"running":False,"kill_switch":True,"last_action":"KILL_SWITCH:"+reason,"kill_reason":reason,"reconciled":False})
    logger.error("EMA_AUTO_KILL_SWITCH reason=%s",reason)

async def _check_daily_limits(equity):
    if AUTO_STATE.get("kill_switch"): return False
    today=datetime.now(timezone.utc).date().isoformat()
    if AUTO_STATE.get("utc_day")!=today:
        AUTO_STATE.update({"utc_day":today,"trades_today":0,"daily_start_equity":equity})
    start=float(AUTO_STATE.get("daily_start_equity") or equity)
    if start<=0 or equity<=0: raise RuntimeError("Cannot verify DEMO equity; fail-closed")
    loss=(start-equity)/start
    AUTO_STATE["daily_loss_pct"]=round(loss*100,4)
    if loss>=AUTO_DAILY_LOSS_LIMIT:
        await _kill_switch("DAILY_LOSS_LIMIT"); return False
    if int(AUTO_STATE.get("consecutive_losses",0))>=AUTO_MAX_CONSECUTIVE_LOSSES:
        await _kill_switch("CONSECUTIVE_LOSSES"); return False
    if AUTO_STATE["trades_today"]>=AUTO_MAX_TRADES_PER_DAY:
        AUTO_STATE["last_action"]="DAILY_TRADE_LIMIT"; return False
    return True

async def strategy_frame(account_id,symbol,timeframe,hours):
    key=(symbol,timeframe,hours)
    cached=CANDLE_CACHE.get(key)
    if cached and time.time()-cached["fetched_at"]<CANDLE_CACHE_TTL.get(timeframe,15):
        rows=list(cached.get("candles",[]))
    else:
        payload=await ta("GET",f"/v1/accounts/{account_id}/candles?symbol={symbol}&timeframe={timeframe}&hours={hours}")
        rows=payload.get("candles",[]) if isinstance(payload,dict) else []
    clean=[]
    for bar in rows:
        try:
            clean.append({"timestamp":float(bar["timestamp"]),"open":float(bar["open"]),"high":float(bar["high"]),"low":float(bar["low"]),"close":float(bar["close"]),"tick_volume":float(bar.get("tickVolume",bar.get("tick_volume",0)) or 0),"spread":float(bar.get("spread") or 0)})
        except (KeyError,TypeError,ValueError): continue
    clean.sort(key=lambda x:x["timestamp"])
    seconds=AUTO_CANDLE_SECONDS[timeframe]
    clean=[x for x in clean if x["timestamp"]+seconds<=time.time()]
    if len(clean)<205: raise RuntimeError(f"Not enough CLOSED {timeframe} OHLC candles for EMA200: {len(clean)}")
    return pd.DataFrame(clean)

async def _sync_consecutive_losses(account_id,symbol):
    """Read broker closed history; count consecutive EMA bot losses, newest first."""
    checked=AUTO_STATE.get("last_history_loss_check")
    if checked and (datetime.now(timezone.utc)-datetime.fromisoformat(checked)).total_seconds()<30: return
    data=await ta("GET",f"/v1/accounts/{account_id}/history?limit=100")
    history=data.get("history",data.get("trades",[])) if isinstance(data,dict) else data
    if not isinstance(history,list): raise RuntimeError("Invalid closed history payload")
    candidates=[]
    for trade in history:
        if not isinstance(trade,dict): continue
        comment=str(trade.get("comment") or "")
        if "DioMasteR AUTO EMA" not in comment: continue
        if str(trade.get("symbol") or symbol)!=symbol: continue
        pnl=None
        for key in ("profit","realizedProfit","profitLoss","netProfit","pnl"):
            if trade.get(key) is not None:
                try: pnl=float(trade[key]); break
                except (TypeError,ValueError): pass
        if pnl is None: continue
        stamp=trade.get("closeTime",trade.get("closedAt",trade.get("time",trade.get("timestamp",0))))
        candidates.append((str(stamp),pnl))
    candidates.sort(key=lambda x:x[0],reverse=True)
    streak=0
    for _,pnl in candidates:
        if pnl<0: streak+=1
        else: break
    AUTO_STATE["consecutive_losses"]=streak
    AUTO_STATE["last_history_loss_check"]=datetime.now(timezone.utc).isoformat()

async def auto_cycle():
    row,detail=await account_detail()
    if not _is_demo(detail.get("isDemo")): raise HTTPException(403,"DEMO verification failed")
    equity=float((detail.get("account") or {}).get("equity") or 0)
    if not await _check_daily_limits(equity): return
    symbols=(await ta("GET",f"/v1/accounts/{row['id']}/symbols")).get("symbols",[])
    symbol=choose_symbol(symbols)
    await _sync_consecutive_losses(row["id"],symbol)
    if int(AUTO_STATE.get("consecutive_losses",0))>=AUTO_MAX_CONSECUTIVE_LOSSES:
        await _kill_switch("CONSECUTIVE_LOSSES"); return
    if symbol not in SYMBOLS and symbol not in symbols: raise HTTPException(403,"Symbol is not allow-listed")
    tf=StrategyConfig().timeframe
    if tf not in AUTO_CANDLE_SECONDS: raise RuntimeError("Unsupported EMA timeframe")
    if AUTO_TREND_TIMEFRAME not in AUTO_CANDLE_SECONDS:
        raise RuntimeError("Unsupported higher-timeframe trend filter")
    frame=await strategy_frame(row["id"],symbol,tf,int(os.getenv("DIO_EMA_HISTORY_HOURS","2400")))
    trend_frame=await strategy_frame(row["id"],symbol,AUTO_TREND_TIMEFRAME,int(os.getenv("DIO_EMA_TREND_HISTORY_HOURS","2400")))
    q=LIVE_TICKS.get(symbol)
    if not q or q.get("stale") or time.time()-float(q.get("received_at",0))>15:
        AUTO_STATE["last_action"]="BLOCKED_NO_FRESH_TICK"; return
    spread=float(q["ask"])-float(q["bid"])
    signal=await asyncio.to_thread(get_signal,frame,StrategyConfig(),spread,_news_blocked(),trend_frame)
    stamp=float(signal.candle_time or 0)
    AUTO_STATE.update({"last_cycle_at":datetime.now(timezone.utc).isoformat(),"last_bar_time":stamp,"last_signal":{"direction":signal.direction,"reason":signal.reason,"close":signal.close,"ema_fast":signal.ema_fast,"ema_slow":signal.ema_slow,"ema_trend":signal.ema_trend,"adx":signal.adx,"atr":signal.atr,"stop_loss":signal.stop_loss,"take_profit":signal.take_profit},"last_error":None})
    if stamp<=0 or stamp==AUTO_STATE.get("last_processed_candle"):
        AUTO_STATE["last_action"]="WAITING_FOR_NEW_CLOSED_CANDLE"; return
    AUTO_STATE["last_processed_candle"]=stamp
    rows=await reconcile_orders(row["id"])
    symbol_positions=[p for p in rows if str(p.get("symbol",""))==symbol]
    bot=_bot_positions(rows)
    if symbol_positions:
        if bot and signal.direction in ("BUY","SELL") and signal.direction!=str(bot[0].get("side","")).upper():
            for existing in bot:
                ticket=int(existing.get("ticket") or 0)
                if not ticket: raise RuntimeError("Opposite signal: missing broker ticket")
                await ta("DELETE",f"/v1/accounts/{row['id']}/positions/{ticket}",{},idem=True,idempotency_key=f"ema-exit-{symbol}-{stamp:.0f}-{ticket}")
            AUTO_STATE.update({"known_ticket":None,"known_tickets":[],"last_action":"CLOSED_ON_OPPOSITE_SIGNAL"}); return
        AUTO_STATE["last_action"]="TWO_POSITION_RULE_BLOCKED_ENTRY"; return
    if signal.direction not in ("BUY","SELL"):
        AUTO_STATE["last_action"]="HOLD_"+signal.reason; return
    if datetime.now(timezone.utc).weekday()>=5:
        AUTO_STATE["last_action"]="WEEKEND_ENTRY_BLOCKED"; return
    if not EXECUTION_ENABLED:
        AUTO_STATE["last_action"]="SIGNAL_ONLY_EXECUTION_DISABLED"; return
    if AUTO_STATE.get("kill_switch"): return
    candle_key=f"{symbol}:{tf}:{stamp:.0f}"
    if AUTO_STATE.get("last_order_key")==candle_key:
        AUTO_STATE["last_action"]="DUPLICATE_CANDLE_BLOCKED"; return
    price=float(q["ask"] if signal.direction=="BUY" else q["bid"])
    sl=signal.stop_loss; tp=signal.take_profit
    if (signal.direction=="BUY" and not sl<price<tp) or (signal.direction=="SELL" and not tp<price<sl):
        AUTO_STATE["last_action"]="BLOCKED_INVALID_SERVER_SL_TP"; return
    spec_data=await ta("GET",f"/v1/accounts/{row['id']}/symbols/{symbol}/spec")
    spec=spec_data.get("spec",{}) if isinstance(spec_data,dict) else {}
    tick_size=float(spec.get("tickSize") or 0); tick_value=float(spec.get("tickValueAccount") or 0)
    vol_min=float(spec.get("volumeMin") or 0); vol_step=float(spec.get("volumeStep") or 0); vol_max=float(spec.get("volumeMax") or 0)
    if min(tick_size,tick_value,vol_min,vol_step,vol_max)<=0:
        AUTO_STATE["last_action"]="BLOCKED_UNKNOWN_CONTRACT_SPEC"; return
    combined_budget=equity*MAX_RISK_FRACTION
    leg_budget=combined_budget/2.0
    risk_per_lot=(abs(price-sl)/tick_size)*tick_value
    volume=min(MAX_VOLUME,vol_max,leg_budget/risk_per_lot)
    volume=round((volume-vol_min)//vol_step*vol_step+vol_min,8)
    if volume<vol_min or volume>vol_max or volume<=0 or risk_per_lot*volume>leg_budget+1e-8:
        AUTO_STATE["last_action"]="BLOCKED_RISK_CAP_OR_MIN_VOLUME_FOR_TWO_LEGS"; return
    import hashlib
    base_key="EMA"+hashlib.sha256(candle_key.encode()).hexdigest()[:24]
    AUTO_STATE["last_order_key"]=candle_key
    opened=[]
    for leg in ("FAST","RUNNER"):
        order_key=base_key+leg
        req=Order(symbol=symbol,side=signal.direction,volume=volume,stop_loss=sl,take_profit=tp,client_order_id=order_key,order_origin="AUTO")
        result=await order(req,authorization="Bearer "+BRIDGE_TOKEN)
        ticket=int(result.get("order") or 0)
        if not ticket: raise RuntimeError("Broker did not confirm the "+leg+" position ticket")
        opened.append({"leg":leg,"ticket":ticket,"result":result})
        AUTO_STATE.update({"known_ticket":ticket,"known_tickets":[x["ticket"] for x in opened],"broker_bot_positions":len(opened),"last_action":"OPENED_"+signal.direction+"_"+leg})
    AUTO_STATE.update({"trades_today":AUTO_STATE["trades_today"]+2,"last_action":"OPENED_TWO_"+signal.direction,"last_orders":opened})

async def _auto_runner():
    while AUTO_STATE["running"]:
        try: await auto_cycle()
        except asyncio.CancelledError: raise
        except Exception as exc:
            AUTO_STATE.update({"last_error":str(exc)[:300],"last_action":"BLOCKED_ERROR"})
            logger.exception("EMA AUTO cycle failed")
            if "order" in str(exc).lower() or "timeout" in str(exc).lower():
                await _kill_switch("UNCERTAIN_ORDER_OUTCOME")
        await asyncio.sleep(5)

@app.post("/v1/auto/start")
async def auto_start(authorization:Optional[str]=Header(default=None)):
    global AUTO_TASK
    auth(authorization); row,detail=await account_detail()
    if not _is_demo(detail.get("isDemo")): raise HTTPException(403,"AUTO is DEMO-only")
    if not EXECUTION_ENABLED: raise HTTPException(423,"DEMO execution is disabled in Render; no orders can be sent")
    if AUTO_STATE.get("kill_switch"): raise HTTPException(423,"Kill switch active; manual review/reset required")
    await reconcile_orders(row["id"])
    async with AUTO_LOCK:
        if AUTO_TASK and not AUTO_TASK.done():
            return {"ok":True,"running":True,"account_mode":"DEMO","state":AUTO_STATE}
        AUTO_STATE.update({"running":True,"last_action":"STARTING","last_error":None})
        AUTO_TASK=asyncio.create_task(_auto_runner(),name="diomaster-ema-auto")
    return {"ok":True,"running":True,"account_mode":"DEMO","strategy":"EMA_CROSSOVER","timeframe":AUTO_TIMEFRAME}

@app.get("/public/auto/health")
async def public_auto_health():
    """Read-only, credential-free AUTO diagnostics; never exposes account IDs or secrets."""
    signal=AUTO_STATE.get("last_signal") or {}
    return {
        "ok":True,
        "running":bool(AUTO_TASK and not AUTO_TASK.done() and AUTO_STATE.get("running")),
        "account_mode":"DEMO",
        "strategy":"EMA_CROSSOVER",
        "execution_enabled":EXECUTION_ENABLED,
        "last_action":str(AUTO_STATE.get("last_action") or "UNKNOWN")[:80],
        "last_cycle_at":AUTO_STATE.get("last_cycle_at"),
        "last_signal_direction":str(signal.get("direction") or "WAIT")[:12],
        "last_signal_reason":str(signal.get("reason") or "")[:160],
        "last_signal_close":signal.get("close"),
        "last_signal_ema_fast":signal.get("ema_fast"),
        "last_signal_ema_slow":signal.get("ema_slow"),
        "last_signal_ema_trend":signal.get("ema_trend"),
        "last_signal_adx":signal.get("adx"),
        "last_signal_atr":signal.get("atr"),
        "adx_threshold":StrategyConfig().adx_min,
        "cross_lookback_bars":StrategyConfig().cross_lookback_bars,
        "timeframe":StrategyConfig().timeframe,
        "trend_timeframe":AUTO_TREND_TIMEFRAME,
        "last_error_present":bool(AUTO_STATE.get("last_error")),
        "kill_switch":bool(AUTO_STATE.get("kill_switch")),
        "reconciled":bool(AUTO_STATE.get("reconciled")),
        "max_auto_positions":MAX_BOT_POSITIONS,
    }

@app.get("/v1/auto/status")
async def auto_status(authorization:Optional[str]=Header(default=None)):
    auth(authorization); await account_detail()
    return {**AUTO_STATE,"running":bool(AUTO_TASK and not AUTO_TASK.done() and AUTO_STATE["running"]),"account_mode":"DEMO","supported":True,"execution_enabled":EXECUTION_ENABLED,"strategy":"EMA_CROSSOVER","mode":"EMA_CROSSOVER","timeframe":AUTO_TIMEFRAME,"trend_timeframe":AUTO_TREND_TIMEFRAME,"max_auto_positions":MAX_BOT_POSITIONS,"risk_cap_fraction":MAX_RISK_FRACTION,"fast_ema":StrategyConfig().fast_ema,"slow_ema":StrategyConfig().slow_ema,"trend_ema":StrategyConfig().trend_ema,"adx_min":StrategyConfig().adx_min,"sl_atr":StrategyConfig().sl_atr,"tp_atr":StrategyConfig().tp_atr}

@app.post("/v1/auto/stop")
async def auto_stop(authorization:Optional[str]=Header(default=None)):
    global AUTO_TASK
    auth(authorization); AUTO_STATE.update({"running":False,"last_action":"STOPPED","reconciled":False})
    if AUTO_TASK and not AUTO_TASK.done():
        AUTO_TASK.cancel()
        try: await AUTO_TASK
        except asyncio.CancelledError: pass
    return {"running":False,"account_mode":"DEMO","message":"EMA AUTO stopped; broker SL/TP remain active"}

@app.post("/v1/auto/kill")
async def auto_kill(authorization:Optional[str]=Header(default=None)):
    global AUTO_TASK
    auth(authorization)
    await _kill_switch("MANUAL_KILL_SWITCH")
    if AUTO_TASK and not AUTO_TASK.done():
        AUTO_TASK.cancel()
        try: await AUTO_TASK
        except asyncio.CancelledError: pass
    return {"running":False,"kill_switch":True,"account_mode":"DEMO","message":"Kill switch latched; manual reset and reconciliation required"}

@app.post("/v1/auto/kill/reset")
async def reset_kill_switch(authorization:Optional[str]=Header(default=None)):
    auth(authorization)
    if AUTO_STATE.get("running"): raise HTTPException(423,"Stop AUTO before resetting kill switch")
    AUTO_STATE.update({"kill_switch":False,"kill_reason":None,"consecutive_losses":0,"last_action":"KILL_SWITCH_RESET_REQUIRES_RECONCILIATION","reconciled":False})
    return {"ok":True,"running":False,"account_mode":"DEMO","message":"Kill switch reset; reconciliation required before AUTO start"}

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
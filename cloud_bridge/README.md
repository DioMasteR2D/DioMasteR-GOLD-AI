# DioMasteR GOLD AI — TickerAll Vantage MT5 DEMO bridge

This service connects the Android application to a Vantage MT5 DEMO account through the TickerAll REST API. The TickerAll API key and the separate app bridge token stay in Render environment secrets; neither is compiled into the APK.

## Render configuration
- Root directory: repository root
- Build: `pip install -r cloud_bridge/requirements.txt`
- Start: `cd cloud_bridge && uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health check: `/health`

## Required Render secrets and settings
- `TICKERALL_API_KEY`: TickerAll bearer API key.
- `DIO_BRIDGE_TOKEN`: long random bearer token entered once in the Android app.
- `TICKERALL_ACCOUNT_ID`: optional exact TickerAll account ID when more than one matching Vantage DEMO account exists.
- `TICKERALL_SERVER`: exact broker server name; default `VantageMarkets-Demo`.
- `DIO_MT5_ALLOWED_SYMBOLS`: allowed broker-native symbols.
- `DIO_MT5_DEMO_EXECUTION_ENABLED`: remains false until the account's actual symbol contract and risk sizing have been verified.
- `DIO_MT5_MAX_VOLUME`, `DIO_MT5_MAX_RISK_FRACTION`, `DIO_MT5_MAX_POSITIONS`: server-side execution caps.

Never store the TickerAll key or broker password in the Android app, GitHub, or logs. This bridge rejects accounts unless both the linked account record and the live account details identify it as MT5 DEMO on the configured Vantage server.

## Endpoints
All endpoints except `/health` require `Authorization: Bearer <DIO_BRIDGE_TOKEN>`.
- `GET /health`: service health.
- `GET /v1/status`: live MT5 DEMO identity and connection status.
- `GET /v1/quote/{symbol}`: last M1 candle close, explicitly not a bid/ask tick.
- `GET /v1/candles/{symbol}?timeframe=M15&hours=48`: normalized broker OHLC candles and completeness metadata.
- `GET /v1/positions`: live broker open positions.
- `GET /v1/history?symbol=XAUUSD&limit=50`: broker closed-trade history.
- `POST /v1/order`: guarded manual DEMO market order; execution stays disabled by default.
- `POST /v1/positions/{ticket}/close`: guarded close of a DioMasteR-tagged DEMO position.
- `/v1/auto/*`: explicitly reports that cloud auto-execution is not available until a persistent worker, broker tick feed, verified contract sizing, and restart-safe risk state are implemented.

The Render Free plan can sleep when idle. It is not an always-on unattended trading host. The Android UI must show stale/offline status honestly rather than claiming a live connection.

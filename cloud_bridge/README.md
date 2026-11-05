# DioMasteR GOLD AI — MetaApi Cloud DEMO bridge

This service connects the Android app to a Vantage MT5 DEMO account through MetaApi Cloud. It does not require a user-managed Windows PC/VPS. It is a separate Linux-compatible service; do not deploy the legacy `bridge/` folder to Render because that service imports the Windows-only MetaTrader5 terminal package.

## Required Render environment secrets
- `METAAPI_TOKEN`: MetaApi API token (secret)
- `METAAPI_ACCOUNT_ID`: ID of the Vantage MT5 account added to MetaApi
- `DIO_BRIDGE_TOKEN`: a separate long random token entered in the Android app
- `METAAPI_CLIENT_API`: optional regional client API URL; default is New York
- `DIO_MT5_ALLOWED_SYMBOLS`: exact broker symbol, e.g. XAUUSD or XAUUSD.
- `DIO_MT5_MAX_VOLUME`: default 0.01 lots
- `DIO_MT5_MAX_RISK_FRACTION`: default 0.0025 (0.25%)
- `DIO_MT5_MAGIC`: default 26051105
- `DIO_MT5_DEMO_EXECUTION_ENABLED`: default false; set true only after the account information endpoint confirms DEMO and a broker quote/specification has been verified.

Never place MetaApi or broker credentials in Android, GitHub, chat, or source control. Configure the MT5 account in MetaApi using its secure end-user configuration link. Use a DEMO account only.

## Deploy
Root directory: `cloud_bridge`
Build command: `pip install -r requirements.txt`
Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
Use a continuously running paid Render web service for unattended availability; free services can sleep.

## Endpoints
Authenticated endpoints use `Authorization: Bearer <DIO_BRIDGE_TOKEN>`.
- GET `/health`
- GET `/v1/status` — refuses anything except a MetaApi account reporting `ACCOUNT_TRADE_MODE_DEMO` or `DEMO`, and requires a connected terminal
- GET `/v1/quote/{symbol}`
- GET `/v1/positions`
- POST `/v1/order` — market BUY/SELL with mandatory absolute SL/TP, broker volume-step validation, allowlisted symbol, 0.25% equity risk cap, and fixed max volume
- POST `/v1/positions/{ticket}/close` — only closes positions with the configured bot magic number
- Auto endpoints explicitly report unsupported; no fake auto-running status is returned.

This first cloud version supports **manual app-initiated DEMO orders**. Automatic strategy execution is not enabled until candle-based strategy logic, position reconciliation, duplicate-order protection, and cloud kill-switch behavior have been implemented and tested. No LIVE trading path exists.

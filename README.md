# DioMasteR GOLD AI

Native Android XAUUSD trading dashboard with a MetaApi Cloud connection to a Vantage MT5 DEMO account.

## Android release 2.5.0
- Native Android interface, animated gold dashboard and indicative XAU/USD spot chart.
- Paper trading remains available.
- Optional authenticated MetaApi Cloud bridge connection for Vantage MT5 DEMO.
- App BUY/SELL controls send manual broker orders only when the cloud bridge confirms a connected DEMO account and execution is enabled.
- Orders require broker-valid volume, mandatory server-side Stop Loss and Take Profit, an allow-listed gold symbol, and a 0.25% equity risk cap (cloud bridge).
- MT5 positions can be viewed and bot-owned positions can be closed.
- No LIVE trading path exists. The bridge fails closed if the account is not explicitly identified as DEMO.

## Cloud bridge
The Linux-compatible service is in `cloud_bridge/`. It does not use the Windows-only MetaTrader5 Python package and does not require the user's PC or Windows VPS.

Deploy it as a separate Render web service with root directory `cloud_bridge`, build command `pip install -r requirements.txt`, and start command `uvicorn main:app --host 0.0.0.0 --port $PORT`. A continuously running paid service is required for unattended availability; free instances may sleep.

Set these secrets in Render, never in the APK or GitHub:
- `METAAPI_TOKEN`
- `METAAPI_ACCOUNT_ID`
- `DIO_BRIDGE_TOKEN` (generate a long random secret)
- Optional: `METAAPI_CLIENT_API` for the MetaApi region
- `DIO_MT5_ALLOWED_SYMBOLS` exact Vantage symbol (e.g. XAUUSD or XAUUSDm)
- `DIO_MT5_MAX_VOLUME` (default 0.01)
- `DIO_MT5_MAX_RISK_FRACTION` (default 0.0025)
- `DIO_MT5_DEMO_EXECUTION_ENABLED` (default false; enable only after MetaApi has confirmed the Vantage DEMO account and the quote/specification are verified)

Configure the broker account in MetaApi using its secure end-user configuration link. Do not send broker passwords or MetaApi tokens in chat. The Android app receives only the Render HTTPS URL and the separate `DIO_BRIDGE_TOKEN`.

## Current scope and limitations
- Manual BUY/SELL from the Android app is supported by the cloud bridge once deployment and MetaApi account configuration are complete.
- Cloud auto-start endpoints deliberately report unsupported. The old Windows auto loop is not used by this cloud service. Automatic strategy execution will only be enabled after candle-based strategy logic, order reconciliation, duplicate-order protection, kill switch and broker-specific DEMO validation are complete.
- The Android AI panel is a deterministic signal helper, not a trained machine-learning model; its current spot sampling is not a substitute for broker M5 OHLC candles.
- MetaApi is a third-party paid cloud service. This repository change does not create a MetaApi subscription, provision the broker account, deploy Render, or place an order.
- This build has not yet been verified against the user's Vantage account. Confirm the account's exact server and symbol before enabling execution.

## Legacy bridge
The original `bridge/` folder remains for Windows MT5 terminal use. Do not deploy it to Linux Render; it imports the Windows terminal integration.

## Build
GitHub Actions runs Android unit tests and builds the debug APK artifact.

# DioMasteR GOLD AI — MT5 Demo Bridge (read-only)

Runs on Windows beside a logged-in MetaTrader 5 desktop terminal. It exposes authenticated, read-only account status, broker quote and open positions.

## Safety
- Every private endpoint requires a Bearer token configured as DIO_BRIDGE_TOKEN.
- Every private endpoint re-checks the MT5 account and accepts DEMO only (trade_mode == 0). LIVE and contest accounts are rejected.
- There is deliberately no order-send, modify or close endpoint. execution_enabled is always false.
- Binds to localhost by default. For Android remote access use a private VPN or HTTPS reverse proxy; never expose port 8787 directly to the public internet.
- Android rejects plain HTTP URLs.

## Windows setup
1. Install Python 3.11 (64-bit) and MetaTrader 5 desktop.
2. Log in to a broker DEMO account in MT5.
3. In PowerShell inside this folder run:
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   $env:DIO_BRIDGE_TOKEN = "use-a-long-random-secret"
   py bridge.py
4. Keep MT5 open and logged in. The service listens on 127.0.0.1:8787.
5. To connect Android, expose it only through a private VPN/HTTPS tunnel and enter that HTTPS URL in the app.

## API
- GET /health — process health.
- GET /v1/status — authenticated DEMO account status; rejects LIVE/contest.
- GET /v1/quote/XAUUSD — authenticated broker bid/ask; broker symbol may differ (e.g. XAUUSDm).
- GET /v1/positions — authenticated open positions.
- Header: Authorization: Bearer <DIO_BRIDGE_TOKEN>.

Integration scaffold only: not yet tested against your broker terminal or deployed Windows VPS. Android paper trading remains independent. No live execution is possible through this bridge.

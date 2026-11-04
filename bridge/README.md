# DioMasteR GOLD AI — Vantage / MetaTrader 5 DEMO bridge

This companion service runs on a **Windows PC or Windows VPS** with the Vantage MetaTrader 5 desktop terminal installed and logged in to a Vantage **DEMO** account. It now supports guarded demo market orders, position reads, and closing only bot-owned positions.

## Safety rules (do not remove)
- Every private request requires the Bearer token `DIO_BRIDGE_TOKEN`.
- Every private request rechecks the active MT5 account and accepts only `trade_mode == 0` (DEMO). LIVE and contest accounts are rejected.
- Order execution is disabled by default. It requires the explicit Windows environment setting `DIO_MT5_DEMO_EXECUTION_ENABLED=true`.
- Only symbols in `DIO_MT5_ALLOWED_SYMBOLS` can be traded. Set the exact Vantage symbol shown in Market Watch, e.g. `XAUUSD` or `XAUUSDm`.
- Volume is capped by `DIO_MT5_MAX_VOLUME` (default 0.10 lots). The bridge validates broker min/step and requires server-side Stop Loss and Take Profit on every new order.
- New orders are checked with MT5 `order_check` before `order_send`. No LIVE order endpoint exists.
- Close endpoint only closes positions carrying this bridge's configured magic number.
- Bind to localhost by default. For Android remote access, use a private VPN or authenticated HTTPS reverse proxy. Never expose port 8787 directly to the public internet.
- Never share your Vantage password or MT5 investor/master password in chat or put them in the Android app.

## Windows / Vantage DEMO setup
1. Install Python 3.11 64-bit and the Vantage MetaTrader 5 desktop terminal.
2. Log in to a Vantage **Demo** trading account in MT5. Confirm the account says Demo and XAUUSD is visible in Market Watch.
3. Open PowerShell in this folder:
   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
4. Set a long random bridge token and the exact broker symbol:
   ```powershell
   $env:DIO_BRIDGE_TOKEN = "replace-with-a-long-random-secret"
   $env:DIO_MT5_ALLOWED_SYMBOLS = "XAUUSD"
   $env:DIO_MT5_MAX_VOLUME = "0.05"
   $env:DIO_MT5_DEMO_EXECUTION_ENABLED = "true"
   py bridge.py
   ```
   If Vantage names gold `XAUUSDm`, change the allow-list to that exact symbol. Start with a low demo volume cap; the app's order sizing must also respect the broker contract specification.
5. Keep MT5 open, logged in, connected, and Algo Trading enabled. The bridge listens on `127.0.0.1:8787`.
6. To reach it from Android, connect both devices through a private VPN (recommended) or a properly authenticated HTTPS reverse proxy. Enter that HTTPS URL and the bridge token in the Android app.

## API (all except /health require Bearer auth)
- `GET /health` — process health only.
- `GET /v1/status` — account mode, server, equity and execution flag.
- `GET /v1/quote/{symbol}` — broker bid/ask for an allow-listed symbol.
- `GET /v1/positions` — current MT5 positions.
- `POST /v1/order` — DEMO market BUY/SELL with mandatory server-side SL/TP.
- `POST /v1/positions/{ticket}/close` — closes only positions with the configured bot magic number.

Example order body:
```json
{
  "symbol": "XAUUSD",
  "side": "BUY",
  "volume": 0.01,
  "stop_loss": 2300.00,
  "take_profit": 2324.00,
  "client_order_id": "android-demo-unique-0001"
}
```
Use live broker bid/ask and symbol specifications to calculate valid prices and volume; the example prices are illustrative only.

## Important limitations
- The bridge must run on Windows with the actual MT5 terminal; it cannot run on Android, Netlify, or a Linux-only Render service.
- A running bridge and a reachable private HTTPS/VPN route are prerequisites for Android commands.
- This repository update adds the guarded server-side DEMO execution API. It does **not** mean a Vantage account has already been connected or that an order has been tested. Test with the Vantage demo account first and verify the resulting ticket in MT5.
- Do not switch to a LIVE account. The bridge rejects it.

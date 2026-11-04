# DioMasteR GOLD AI

Native Android application for XAUUSD paper trading. The app is no longer a WebView mock-up: the market screen, chart, buttons, position list, risk controls and trade history are built with native Android views.

## Current Android release
- Native Android UI, custom gold launcher icon, minimum Android 6.0 (API 23).
- Public XAU/USD spot reference feed from Gold-API.com, refreshed every 30 seconds while the app is active.
- $10,000 virtual account; open positions, closed trades and pause state are stored locally on the device.
- Manual paper BUY/SELL, individual close and close-all controls.
- Automatic paper stop-loss / take-profit monitoring on received quotes.
- Deterministic risk governor: 0.5% risk budget, max 5.0 oz per position, max 3 open positions, $200 daily loss guard and 5% peak-equity drawdown guard.
- New entries fail closed when the quote is missing/stale, trading is paused or a risk limit is reached.
- Unit tests cover risk sizing and the main entry guards.

## Reference architecture
The design takes inspiration from the separation of concerns in [MooreSi/forex-gold](https://github.com/MooreSi/forex-gold): a deterministic risk governor before execution, a separate trade lifecycle manager, explicit pause/halt controls and a recorded trade ledger. This repository is an independent Android implementation; it does not copy the reference source code. The reference repository is licensed AGPL-3.0.

## Important limitations — read before use
- This is **paper trading only**. There are no real broker orders, no wallet and no live execution switch.
- Gold-API.com provides an indicative spot reference, not the broker's executable XAUUSD CFD bid/ask, spread or commission. Paper fills use the received reference price and do not model spread, slippage, swaps or fees.
- The Android app checks stops and targets while it is running and receiving fresh quotes. Android may suspend or kill an app in the background; this is not a guaranteed unattended stop-loss service.
- Android 2.1.0 adds an HTTPS MT5 bridge connection check. It verifies the bridge token, terminal heartbeat and DEMO account mode; it does not send broker orders or import positions into the paper ledger.
- The AI signal engine is not active. The app reports that honestly.

## MT5 Demo bridge — read-only companion added
The repository now includes a Windows companion service in `bridge/`. It provides authenticated `/v1/status`, `/v1/quote/{symbol}` and `/v1/positions` read endpoints. Every private request re-checks the MT5 account and rejects LIVE or contest accounts. There is intentionally no order submission endpoint. The Android app accepts HTTPS bridge URLs only and verifies `account_mode=DEMO`, terminal heartbeat and `execution_enabled=false`.

The bridge is a scaffold and still needs to be installed on a Windows PC/VPS with your MT5 DEMO terminal and broker-specific symbol. It has not been tested against a live terminal or deployed HTTPS tunnel.

## MT5 Demo bridge — deployment requirements
MetaTrader 5's Python integration runs alongside a desktop MT5 terminal on Windows, not directly inside an Android APK. A proper connection requires a separate PC/VPS bridge, authenticated app-to-bridge transport, broker-specific bid/ask and candle data, account-mode verification (DEMO only), order reconciliation, heartbeat and a kill switch. The bridge must reject LIVE accounts and must not accept an order until the user explicitly approves the demo connection. The service is not yet deployed or tested against your broker.

## Build and tests
GitHub Actions runs `testDebugUnitTest` and `assembleDebug`, verifies the APK exists and uploads `DioMasteR-GOLD-AI-debug-APK`.

APK output: `app/build/outputs/apk/debug/app-debug.apk`.

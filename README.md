# DioMasteR GOLD AI

Greek-language Android app for XAUUSD with a black-and-gold interface.

## Current release scope
- Android WebView shell; minimum Android 6.0 (API 23).
- Public XAU spot reference feed from Gold-API.com, refreshed every 30 seconds.
- $10,000 virtual account with locally persisted paper positions and trade history.
- Manual demo BUY/SELL, automatic stop-loss/take-profit monitoring, position sizing, 0.5% risk budget per trade, maximum 3 open positions, $200 daily loss guard, and 5% equity drawdown guard.
- EMA 9/21 session trend hint after enough samples; informational only, not an AI prediction.
- CSV export of closed paper trades.
- No broker credentials, no MT5 connection, no wallet, and no real order execution.

## Important market-data limitation
The feed is an indicative XAU/USD spot reference. It is not a broker's executable XAUUSD CFD bid/ask quote and may differ from MT5. If the feed is unavailable or stale, new demo positions are blocked. Price history is sampled only while the app is running; the trend hint is not a validated trading strategy.

## Build
GitHub Actions builds a debug APK on every push to `main` and uploads it as the artifact `DioMasteR-GOLD-AI-debug-APK`.

APK output: `app/build/outputs/apk/debug/app-debug.apk`.

## Technical direction
The architecture takes inspiration from risk-governor and position-management concepts in [MooreSi/forex-gold](https://github.com/MooreSi/forex-gold), but this Android demo is an independent implementation. The reference project is AGPL-3.0; its source code is not copied into this repository.

## Next phase
A separate MT5 demo bridge with broker-specific quotes, candle history, backtesting, and audited signal logic must be implemented and tested before considering any live-trading capability. Live trading remains out of scope.

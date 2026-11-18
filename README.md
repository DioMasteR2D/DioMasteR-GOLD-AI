# DioMasteR GOLD AI

Native Android XAUUSD trading dashboard connected to the existing TickerAll service and Vantage MT5 DEMO account.

## Single automatic strategy

The only automatic trading strategy is **EMA Crossover**:
- Symbol: XAUUSD (broker-supported gold alias only when explicitly returned by TickerAll)
- Main timeframe: M15; decisions use completed broker OHLC candles only
- EMA 20 / EMA 50 crossover
- EMA 200 trend filter
- ADX(14) > 20 entry filter
- ATR(14): server-side Stop Loss = 1.5 × ATR; Take Profit = 3 × ATR
- BUY only when EMA20 crosses above EMA50 and close is above EMA200
- SELL only when EMA20 crosses below EMA50 and close is below EMA200
- One open bot position maximum; exit on broker SL/TP or opposite qualified signal

## DEMO-only safety

- TickerAll remains the sole broker/API provider; Vantage MT5 DEMO is verified before account actions.
- No LIVE trading mode or LIVE order path is permitted.
- Maximum risk is capped at 0.25% equity per trade.
- Mandatory broker-side SL/TP, symbol allow-list, spread filter, weekend entry block, optional UTC news windows, per-candle idempotency, order reconciliation, daily loss and consecutive-loss kill switches.
- Manual orders remain separate from AUTO and are subject to the same DEMO and risk gates.

## Cloud service

The Render service is in `cloud_bridge/`:
- Build: `pip install -r cloud_bridge/requirements.txt`
- Start: `cd cloud_bridge && uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health: `/health`

Keep existing TickerAll and bridge secrets only in Render. Never commit or paste credentials into source control or chat.

## Android

The Android application displays the cloud EMA AUTO status and strategy parameters. Its chart indicators use EMA20/EMA50; cloud AUTO remains the sole authority for entry/exit decisions. The old Adaptive Liquidity Hunter, H4/H1 + M15 + M5 strategy display, EMA9/21 strategy display, and alternate legacy MT5 bridge have been removed.

GitHub Actions runs the cloud EMA tests and builds the Android debug APK.

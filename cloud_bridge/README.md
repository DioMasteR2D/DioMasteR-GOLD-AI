# DioMasteR GOLD AI — TickerAll Vantage MT5 DEMO bridge

The existing TickerAll connection, Android API contract, Render service, and existing database are retained. The cloud AUTO strategy is EMA crossover only. No LIVE trading path exists or is permitted.

## Render configuration
- Build: `pip install -r cloud_bridge/requirements.txt`
- Start: `cd cloud_bridge && uvicorn main:app --host 0.0.0.0 --port $PORT`
- Health: `/health`

## Existing secrets — do not replace
Keep the existing `TICKERALL_API_KEY`, `DIO_BRIDGE_TOKEN`, TickerAll account/session settings and broker credentials exactly as currently configured in Render. Never commit secrets.

## EMA strategy configuration
- `DIO_EMA_TIMEFRAME` (default M15; supports M1/M5/M15/M30/H1/H4)
- `DIO_EMA_FAST` (20), `DIO_EMA_SLOW` (50), `DIO_EMA_TREND` (200)
- `DIO_ADX_PERIOD` (14), `DIO_ADX_MIN` (20; current Render override is 15)
- `DIO_EMA_CROSS_LOOKBACK_BARS` (3; accepts a fresh crossover in the last 3 fully closed candles only while EMA alignment and EMA200 trend remain valid)
- `DIO_ATR_PERIOD` (14), `DIO_SL_ATR` (1.5), `DIO_TP_ATR` (3.0)
- `DIO_MAX_SPREAD` (0.50; in XAUUSD price units)
- `DIO_EMA_HISTORY_HOURS` (2400)
- `DIO_AUTO_MAX_TRADES_PER_DAY` (20)
- `DIO_AUTO_MAX_CONSECUTIVE_LOSSES` (3)
- `DIO_AUTO_DAILY_LOSS_LIMIT` (0.05 = 5%)
- `DIO_AUTO_NEWS_WINDOWS_UTC` optional comma-separated UTC time ranges, e.g. `12:55-13:20,17:25-17:50`

## Safety
- Strict DEMO identity check (MT5 and configured Vantage DEMO server); fail closed otherwise.
- Symbol allow-list; one open XAUUSD position maximum.
- Broker-side mandatory SL/TP; risk sizing uses broker tick size/value and is capped at 0.25% equity.
- Entries only on closed broker OHLC candles, with a fresh EMA crossover (up to 3 closed candles old by default), EMA200 trend alignment, ADX and spread checks. The crossover is never reused after the configured lookback.
- Weekend entries blocked. Optional UTC news windows block entries.
- Reconciliation checks bot-tagged broker positions and verifies SL/TP before AUTO start.
- Deterministic per-candle idempotency key is sent to TickerAll.
- Kill switch: `POST /v1/auto/kill`; reset requires explicit `POST /v1/auto/kill/reset` and a fresh reconciliation.
- AUTO remains disabled unless `DIO_MT5_DEMO_EXECUTION_ENABLED=true` is explicitly set in Render. Do not enable until read-only verification and tests are complete.

## Endpoints
- `GET /health`
- `GET /v1/status`
- `GET /v1/candles/{symbol}?timeframe=M15&hours=48`
- `GET /v1/positions`
- `GET /v1/history`
- `POST /v1/auto/start`, `GET /v1/auto/status`, `POST /v1/auto/stop`, `POST /v1/auto/kill`

## Backtest and tests
- `ema_backtest.py`: spread/slippage-aware backtest and chronological in-sample/out-of-sample split.
- Run tests from `cloud_bridge`: `python -m unittest discover -v`.

The Render Free plan may sleep when idle; do not assume continuous unattended execution.

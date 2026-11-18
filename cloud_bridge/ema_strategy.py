"""EMA crossover strategy for XAUUSD DEMO. Operates on completed broker OHLC candles only."""
from dataclasses import dataclass
import os
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class StrategyConfig:
    timeframe: str = os.getenv("DIO_EMA_TIMEFRAME", "M5").upper()
    fast_ema: int = int(os.getenv("DIO_EMA_FAST", "20"))
    slow_ema: int = int(os.getenv("DIO_EMA_SLOW", "50"))
    trend_ema: int = int(os.getenv("DIO_EMA_TREND", "200"))
    adx_period: int = int(os.getenv("DIO_ADX_PERIOD", "14"))
    adx_min: float = float(os.getenv("DIO_ADX_MIN", "20"))
    atr_period: int = int(os.getenv("DIO_ATR_PERIOD", "14"))
    sl_atr: float = float(os.getenv("DIO_SL_ATR", "1.5"))
    tp_atr: float = float(os.getenv("DIO_TP_ATR", "3.0"))
    max_spread: float = float(os.getenv("DIO_MAX_SPREAD", "0.50"))
    news_before_minutes: int = int(os.getenv("DIO_NEWS_BLOCK_BEFORE_MIN", "0"))
    news_after_minutes: int = int(os.getenv("DIO_NEWS_BLOCK_AFTER_MIN", "0"))
    cross_lookback_bars: int = max(1, min(5, int(os.getenv("DIO_EMA_CROSS_LOOKBACK_BARS", "3"))))

@dataclass(frozen=True)
class Signal:
    direction: str
    candle_time: float | None
    close: float = 0.0
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    ema_trend: float = 0.0
    adx: float = 0.0
    atr: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = "insufficient_data"

def _validate(frame: pd.DataFrame, minimum: int, require_timestamp: bool = False):
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("candles must be a pandas DataFrame")
    required = {"open", "high", "low", "close"}
    if require_timestamp:
        required.add("timestamp")
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError("missing OHLC columns: " + ",".join(sorted(missing)))
    if len(frame) < minimum:
        raise ValueError(f"need at least {minimum} candles")
    values = frame[list(required.intersection(frame.columns))].astype(float)
    if not np.isfinite(values.to_numpy()).all():
        raise ValueError("OHLC data contains non-finite values")
    if (frame["high"].astype(float) < frame["low"].astype(float)).any():
        raise ValueError("candle high is below low")

def indicators(frame: pd.DataFrame, config: StrategyConfig = StrategyConfig()) -> pd.DataFrame:
    _validate(frame, 2)
    df = frame.copy().reset_index(drop=True)
    high, low, close = (df[c].astype(float) for c in ("high", "low", "close"))
    df["ema_fast"] = close.ewm(span=config.fast_ema, adjust=False, min_periods=config.fast_ema).mean()
    df["ema_slow"] = close.ewm(span=config.slow_ema, adjust=False, min_periods=config.slow_ema).mean()
    df["ema_trend"] = close.ewm(span=config.trend_ema, adjust=False, min_periods=config.trend_ema).mean()
    prev_close = close.shift(1)
    tr = pd.concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1/config.atr_period, adjust=False, min_periods=config.atr_period).mean()
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    smooth_tr = tr.ewm(alpha=1/config.adx_period, adjust=False, min_periods=config.adx_period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/config.adx_period, adjust=False, min_periods=config.adx_period).mean() / smooth_tr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1/config.adx_period, adjust=False, min_periods=config.adx_period).mean() / smooth_tr.replace(0, np.nan)
    dx = 100 * (plus_di-minus_di).abs() / (plus_di+minus_di).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1/config.adx_period, adjust=False, min_periods=config.adx_period).mean()
    return df

def get_signal(frame: pd.DataFrame, config: StrategyConfig = StrategyConfig(),
               spread: float = 0.0, news_blocked: bool = False,
               trend_frame: pd.DataFrame | None = None) -> Signal:
    minimum = max(config.trend_ema + 2, config.slow_ema + 2, config.adx_period*3, config.atr_period*3)
    try:
        _validate(frame, minimum, require_timestamp=True)
    except (ValueError, TypeError):
        return Signal("HOLD", None, reason="insufficient_or_invalid_ohlc")
    df = indicators(frame, config)
    # The caller must pass only fully closed broker candles; the final row is the latest closed candle.
    prev, cur = df.iloc[-2], df.iloc[-1]
    stamp = float(cur["timestamp"])
    required = ["ema_fast","ema_slow","ema_trend","adx","atr"]
    if any(pd.isna(cur[k]) or pd.isna(prev[k]) for k in required):
        return Signal("HOLD", stamp, reason="indicators_not_ready")
    vals = {k: float(cur[k]) for k in required}
    close = float(cur["close"])
    if news_blocked:
        return Signal("HOLD", stamp, close=close, **vals, reason="news_window")
    if not np.isfinite(spread) or spread < 0 or spread > config.max_spread:
        return Signal("HOLD", stamp, close=close, **vals, reason="spread_filter")
    if vals["adx"] <= config.adx_min:
        return Signal("HOLD", stamp, close=close, **vals, reason="adx_filter")
    # M15 is the higher-timeframe direction filter; M5 supplies the entry timing.
    trend_bias = None
    if trend_frame is not None:
        try:
            trend_minimum = max(config.trend_ema + 2, config.slow_ema + 2, config.adx_period * 3, config.atr_period * 3)
            _validate(trend_frame, trend_minimum, require_timestamp=True)
            higher = indicators(trend_frame, config)
            h = higher.iloc[-1]
            if any(pd.isna(h[k]) for k in ("ema_fast", "ema_slow", "ema_trend")):
                return Signal("HOLD", stamp, close=close, **vals, reason="m15_trend_indicators_not_ready")
            hclose = float(h["close"])
            if float(h["ema_fast"]) > float(h["ema_slow"]) and hclose > float(h["ema_trend"]):
                trend_bias = "BUY"
            elif float(h["ema_fast"]) < float(h["ema_slow"]) and hclose < float(h["ema_trend"]):
                trend_bias = "SELL"
            else:
                trend_bias = "HOLD"
        except (ValueError, TypeError, IndexError):
            return Signal("HOLD", stamp, close=close, **vals, reason="m15_trend_data_invalid")
    # Recover a fresh closed-bar cross if a restart or short feed delay skipped its
    # exact candle. The current EMA relationship and EMA trend must still agree.
    cross_direction = None
    first = max(1, len(df) - config.cross_lookback_bars)
    for i in range(len(df) - 1, first - 1, -1):
        before, after = df.iloc[i - 1], df.iloc[i]
        up = float(before["ema_fast"]) <= float(before["ema_slow"]) and float(after["ema_fast"]) > float(after["ema_slow"])
        down = float(before["ema_fast"]) >= float(before["ema_slow"]) and float(after["ema_fast"]) < float(after["ema_slow"])
        if up or down:
            cross_direction = "BUY" if up else "SELL"
            break
    still_bullish = vals["ema_fast"] > vals["ema_slow"]
    still_bearish = vals["ema_fast"] < vals["ema_slow"]
    local_buy_ok = still_bullish and (trend_frame is not None or close > vals["ema_trend"])
    local_sell_ok = still_bearish and (trend_frame is not None or close < vals["ema_trend"])
    direction = ("BUY" if cross_direction == "BUY" and local_buy_ok
                 else "SELL" if cross_direction == "SELL" and local_sell_ok
                 else "HOLD")
    if trend_bias is not None and direction in ("BUY", "SELL") and direction != trend_bias:
        direction = "HOLD"
    reason = "ema_crossover_confirmed_on_close" if direction in ("BUY", "SELL") else ""
    # Trend-continuation fallback: when EMA20/50/200 are already aligned and
    # ADX confirms strength, allow a closed-candle pullback/reclaim of EMA20.
    # This avoids waiting for a brand-new EMA20/50 cross in an established trend.
    if direction == "HOLD":
        for i in range(len(df) - 1, first - 1, -1):
            before, after = df.iloc[i - 1], df.iloc[i]
            # Accept either a close-to-close reclaim OR an intrabar EMA20
            # rejection confirmed by the closed candle. The previous rule only
            # accepted a prior CLOSE on the other side of EMA20, missing normal
            # wick retests in established trends.
            bull_reclaim = (float(before["close"]) <= float(before["ema_fast"]) and
                            float(after["close"]) > float(after["ema_fast"]))
            bear_reclaim = (float(before["close"]) >= float(before["ema_fast"]) and
                            float(after["close"]) < float(after["ema_fast"]))
            bull_wick_rejection = (float(after["low"]) <= float(after["ema_fast"]) and
                                   float(after["close"]) > float(after["ema_fast"]))
            bear_wick_rejection = (float(after["high"]) >= float(after["ema_fast"]) and
                                   float(after["close"]) < float(after["ema_fast"]))
            # A deeper EMA50 retest is also valid, but only when the same
            # completed candle rejects EMA50 and closes back beyond EMA20
            # in the direction of the established EMA20/50/200 trend.
            bull_ema50_rejection = (float(after["low"]) <= float(after["ema_slow"]) and
                                    float(after["close"]) > float(after["ema_fast"]) and
                                    float(after["close"]) > float(after["open"]))
            bear_ema50_rejection = (float(after["high"]) >= float(after["ema_slow"]) and
                                    float(after["close"]) < float(after["ema_fast"]) and
                                    float(after["close"]) < float(after["open"]))
            bull = (float(after["ema_fast"]) > float(after["ema_slow"]) and
                    (trend_frame is not None or float(after["close"]) > float(after["ema_trend"])) and
                    (bull_reclaim or bull_wick_rejection or bull_ema50_rejection))
            bear = (float(after["ema_fast"]) < float(after["ema_slow"]) and
                    (trend_frame is not None or float(after["close"]) < float(after["ema_trend"])) and
                    (bear_reclaim or bear_wick_rejection or bear_ema50_rejection))
            if bull and still_bullish and (trend_bias in (None, "BUY")) and (trend_frame is not None or close > vals["ema_trend"]):
                direction = "BUY"
                reason = ("ema50_deep_pullback_confirmed_on_close" if bull_ema50_rejection
                          else "ema_trend_pullback_confirmed_on_close")
                break
            if bear and still_bearish and (trend_bias in (None, "SELL")) and (trend_frame is not None or close < vals["ema_trend"]):
                direction = "SELL"
                reason = ("ema50_deep_pullback_confirmed_on_close" if bear_ema50_rejection
                          else "ema_trend_pullback_confirmed_on_close")
                break
    if direction == "HOLD":
        hold_reason = f"no_crossover_or_trend_pullback_within_{config.cross_lookback_bars}_closed_bars"
        if trend_bias == "HOLD":
            hold_reason = "m15_trend_not_aligned"
        elif trend_bias in ("BUY", "SELL") and cross_direction in ("BUY", "SELL") and cross_direction != trend_bias:
            hold_reason = "m5_signal_conflicts_with_m15_trend"
        return Signal("HOLD", stamp, close=close, **vals, reason=hold_reason)
    distance = config.sl_atr * vals["atr"]
    reward = config.tp_atr * vals["atr"]
    sl = close - distance if direction == "BUY" else close + distance
    tp = close + reward if direction == "BUY" else close - reward
    return Signal(direction, stamp, close, vals["ema_fast"], vals["ema_slow"], vals["ema_trend"],
                  vals["adx"], vals["atr"], sl, tp, reason)

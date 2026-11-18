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


def protective_stop(side: str, entry_price: float, current_sl: float,
                    take_profit: float, market_exit_price: float,
                    tick_size: float, config: StrategyConfig = StrategyConfig()) -> float | None:
    """Return a monotonic protective SL; None means no stage is armed or no safe improvement."""
    side = str(side).upper()
    if side not in ("BUY", "SELL"):
        return None
    values = (entry_price, current_sl, take_profit, market_exit_price, tick_size,
              config.sl_atr, config.tp_atr)
    if not all(np.isfinite(float(v)) for v in values) or tick_size <= 0 or config.tp_atr <= 0 or config.sl_atr <= 0:
        return None
    risk = abs(take_profit - entry_price) * config.sl_atr / config.tp_atr
    if risk <= 0 or current_sl <= 0:
        return None
    direction = 1.0 if side == "BUY" else -1.0
    favorable = (market_exit_price - entry_price) * direction
    r_multiple = favorable / risk
    candidate = None
    if r_multiple >= 0.8:
        candidate = entry_price
    if r_multiple >= 1.2:
        candidate = entry_price + direction * 0.3 * risk
    if r_multiple >= 1.5:
        candidate = market_exit_price - direction * 0.8 * risk
    if candidate is None:
        return None
    # Round away from market so the stop remains on the protective side.
    if side == "BUY":
        candidate = np.floor(candidate / tick_size + 1e-9) * tick_size
        if candidate <= current_sl + tick_size * 0.5 or candidate >= market_exit_price:
            return None
    else:
        candidate = np.ceil(candidate / tick_size - 1e-9) * tick_size
        if candidate >= current_sl - tick_size * 0.5 or candidate <= market_exit_price:
            return None
    return float(round(candidate, 10))

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
    # Faster M5 continuation entry: when the closed M15 trend is aligned,
    # accept a decisive M5 candle continuing above/below EMA20 without waiting
    # for another EMA20/50 crossover or a full retest. The ATR distance cap
    # avoids chasing an already-extended candle; all existing risk gates remain.
    if direction == "HOLD" and trend_frame is not None and trend_bias in ("BUY", "SELL"):
        candle = df.iloc[-1]
        body_up = float(candle["close"]) > float(candle["open"])
        body_down = float(candle["close"]) < float(candle["open"])
        near_fast = abs(close - vals["ema_fast"]) <= 0.85 * vals["atr"]
        if (trend_bias == "BUY" and still_bullish and close > vals["ema_fast"]
                and body_up and near_fast):
            direction = "BUY"
            reason = "m5_trend_continuation_confirmed_on_close"
        elif (trend_bias == "SELL" and still_bearish and close < vals["ema_fast"]
                and body_down and near_fast):
            direction = "SELL"
            reason = "m5_trend_continuation_confirmed_on_close"
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

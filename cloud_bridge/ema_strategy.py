"""EMA crossover strategy for XAUUSD DEMO. Operates on completed broker OHLC candles only."""
from dataclasses import dataclass
import os
import numpy as np
import pandas as pd

@dataclass(frozen=True)
class StrategyConfig:
    timeframe: str = os.getenv("DIO_EMA_TIMEFRAME", "M15").upper()
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
               spread: float = 0.0, news_blocked: bool = False) -> Signal:
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
    cross_up = float(prev["ema_fast"]) <= float(prev["ema_slow"]) and vals["ema_fast"] > vals["ema_slow"]
    cross_down = float(prev["ema_fast"]) >= float(prev["ema_slow"]) and vals["ema_fast"] < vals["ema_slow"]
    direction = "BUY" if cross_up and close > vals["ema_trend"] else "SELL" if cross_down and close < vals["ema_trend"] else "HOLD"
    if direction == "HOLD":
        return Signal("HOLD", stamp, close=close, **vals, reason="no_qualified_crossover")
    distance = config.sl_atr * vals["atr"]
    reward = config.tp_atr * vals["atr"]
    sl = close - distance if direction == "BUY" else close + distance
    tp = close + reward if direction == "BUY" else close - reward
    return Signal(direction, stamp, close, vals["ema_fast"], vals["ema_slow"], vals["ema_trend"],
                  vals["adx"], vals["atr"], sl, tp, "ema_crossover_confirmed_on_close")

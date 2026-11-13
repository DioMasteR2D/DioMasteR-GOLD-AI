""""News-only safety gate for XAUUSD. No FRED or macro-data dependency.

The verified USD economic calendar is the sole fundamental safety filter.
High-impact USD events block entries for two hours before and after release.
The primary ForexFactory feed has a TradingView fallback. If neither feed can
be verified, the gate fails closed and blocks entries.
"""
import json
import os
import time
import requests
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

CACHE_FILE = "news_calendar_cache.json"
CACHE_TTL_SECONDS = 3600
EVENTS_SOURCE_OK = False
_LAST_GOOD_EVENTS = None
_LAST_GOOD_AT = 0.0
_LAST_FETCH_ATTEMPT = 0.0
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
TRADINGVIEW_URL = "https://economic-calendar.tradingview.com/events"

@dataclass
class EconomicEvent:
    title: str
    datetime_utc: datetime
    impact: str
    currency: str
    hours_until: float

@dataclass
class FundamentalSignal:
    bias: str
    score: int
    news_block: bool
    news_reason: str
    dxy_signal: str = "NEUTRAL"
    dxy_value: float = None
    dxy_trend: str = "NOT_USED"
    cpi_signal: str = "NEUTRAL"
    cpi_value: float = None
    cpi_mom: float = None
    fed_signal: str = "NEUTRAL"
    fed_rate: float = None
    fed_trend: str = "NOT_USED"
    nfp_signal: str = "NEUTRAL"
    nfp_value: float = None
    upcoming_events: list = None
    details: str = "News calendar only; FRED and macro indicators are disabled"

def _parse_datetime(value):
    """Parse provider timestamps without guessing a local timezone."""
    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 10_000_000_000:
            stamp /= 1000.0
        return datetime.fromtimestamp(stamp, tz=timezone.utc)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None

def _parse_event(item):
    date_value = item.get("date") or item.get("datetime") or item.get("timestamp")
    dt = _parse_datetime(date_value)
    if dt is not None:
        return dt
    date_str = str(item.get("date") or "").strip()
    time_str = str(item.get("time") or "").strip()
    if not date_str:
        return None
    if time_str and time_str.lower() not in ("all day", "tentative", ""):
        for fmt in ("%Y-%m-%d %I:%M%p", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(f"{date_str} {time_str}", fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def _read_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        saved_at = float(payload.get("saved_at", 0))
        if time.time() - saved_at > CACHE_TTL_SECONDS:
            return None
        rows = payload.get("events")
        if not isinstance(rows, list) or not payload.get("verified", False):
            return None
        return rows
    except Exception:
        return None

def _normalize_forexfactory(data):
    if not isinstance(data, list):
        raise RuntimeError("ForexFactory calendar returned an invalid response")
    rows = []
    for item in data:
        if not isinstance(item, dict):
            continue
        currency = str(item.get("currency") or "").upper()
        impact = str(item.get("impact") or "").upper()
        if currency != "USD" or impact not in ("HIGH", "MEDIUM"):
            continue
        dt = _parse_event(item)
        if dt is None:
            continue
        rows.append({"title": str(item.get("title") or "USD event"),
                     "datetime_utc": dt.isoformat(), "impact": impact, "currency": "USD"})
    if not rows and len(data) > 0:
        # A valid week may contain no medium/high USD events; that is still a valid calendar.
        return rows
    return rows

def _fetch_tradingview_events():
    now = datetime.now(timezone.utc)
    params = {
        "from": (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "to": (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "countries": "US",
    }
    response = requests.get(
        TRADINGVIEW_URL,
        params=params,
        headers={"Origin": "https://www.tradingview.com",
                 "Referer": "https://www.tradingview.com/economic-calendar/",
                 "User-Agent": "Mozilla/5.0 DioMasteR-GOLD-AI"},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise RuntimeError("TradingView calendar returned an invalid response")
    rows = []
    for item in data:
        if not isinstance(item, dict):
            continue
        currency = str(item.get("currency") or "").upper()
        country = str(item.get("country") or "").upper()
        importance = item.get("importance", 0)
        try:
            importance = int(importance)
        except (TypeError, ValueError):
            importance = 0
        if currency != "USD" and country not in ("US", "UNITED STATES"):
            continue
        if importance < 2:
            continue
        dt = _parse_event(item)
        if dt is None:
            continue
        rows.append({
            "title": str(item.get("title") or "USD event"),
            "datetime_utc": dt.isoformat(),
            "impact": "HIGH" if importance >= 3 else "MEDIUM",
            "currency": "USD",
        })
    return rows

def _events_from_rows(rows):
    now = datetime.now(timezone.utc)
    events = []
    for row in rows:
        try:
            dt = _parse_datetime(row.get("datetime_utc"))
            if dt is None:
                continue
            hours = (dt - now).total_seconds() / 3600
            if -2 <= hours <= 48:
                events.append(EconomicEvent(str(row["title"]), dt, str(row["impact"]),
                                            str(row["currency"]), round(hours, 2)))
        except Exception:
            continue
    return sorted(events, key=lambda event: event.hours_until)

def _save_verified_cache(rows, source):
    global _LAST_GOOD_EVENTS, _LAST_GOOD_AT, EVENTS_SOURCE_OK
    saved_at = time.time()
    _LAST_GOOD_EVENTS = rows
    _LAST_GOOD_AT = saved_at
    EVENTS_SOURCE_OK = True
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as handle:
            json.dump({"saved_at": saved_at, "verified": True,
                       "source": source, "events": rows}, handle)
    except Exception:
        # The in-memory verified cache remains usable for this process.
        pass

def get_upcoming_events():
    """Return verified high/medium-impact USD events in the next 48 hours."""
    global EVENTS_SOURCE_OK, _LAST_GOOD_EVENTS, _LAST_GOOD_AT, _LAST_FETCH_ATTEMPT
    cached = _read_cache()
    if cached is not None:
        EVENTS_SOURCE_OK = True
        _LAST_GOOD_EVENTS = cached
        _LAST_GOOD_AT = time.time()
        return _events_from_rows(cached)

    now_epoch = time.time()
    if _LAST_GOOD_EVENTS is not None and now_epoch - _LAST_GOOD_AT <= CACHE_TTL_SECONDS:
        EVENTS_SOURCE_OK = True
        return _events_from_rows(_LAST_GOOD_EVENTS)

    if now_epoch - _LAST_FETCH_ATTEMPT < 60:
        EVENTS_SOURCE_OK = False
        raise RuntimeError("USD news calendar refresh is rate-limited; no recent verified cache")
    _LAST_FETCH_ATTEMPT = now_epoch

    primary_error = None
    try:
        response = requests.get(
            CALENDAR_URL,
            headers={"User-Agent": "Mozilla/5.0 DioMasteR-GOLD-AI"},
            timeout=10,
        )
        response.raise_for_status()
        rows = _normalize_forexfactory(response.json())
        _save_verified_cache(rows, "ForexFactory")
        return _events_from_rows(rows)
    except Exception as exc:
        primary_error = exc

    try:
        rows = _fetch_tradingview_events()
        _save_verified_cache(rows, "TradingView")
        return _events_from_rows(rows)
    except Exception as fallback_error:
        EVENTS_SOURCE_OK = False
        raise RuntimeError(
            f"USD news calendar unavailable from ForexFactory ({primary_error}) "
            f"and TradingView ({fallback_error}); entries blocked"
        ) from fallback_error

def is_news_blackout(events, blackout_hours=2.0):
    for event in events:
        if event.impact != "HIGH":
            continue
        hours = event.hours_until
        if 0 < hours <= blackout_hours:
            return True, f"NEWS BLOCK: {event.title} in {hours:.1f}h"
        if -blackout_hours <= hours <= 0:
            return True, f"NEWS BLOCK: {event.title} released {abs(hours):.1f}h ago"
    return False, ""

def get_fundamental_signal():
    """Compatibility API: neutral macro score plus the verified news gate."""
    events = get_upcoming_events()
    blocked, reason = is_news_blackout(events)
    if not EVENTS_SOURCE_OK:
        raise RuntimeError("USD news calendar unavailable; entries blocked")
    return FundamentalSignal(
        bias="NEUTRAL",
        score=0,
        news_block=blocked,
        news_reason=reason,
        upcoming_events=events,
        details="Verified USD news calendar; macro/FRED indicators disabled",
    )

def fundamental_filter_passes(signal, trade_direction):
    if signal.news_block:
        return False, signal.news_reason
    return True, "Verified USD news calendar clear; macro indicators disabled"

def get_fundamental_confluence(signal):
    return "USD NEWS CALENDAR " + ("BLOCKED" if signal.news_block else "CLEAR")

def print_fundamental_report(signal):
    print(f"News calendar: {'BLOCKED — ' + signal.news_reason if signal.news_block else 'CLEAR'}")
    print(signal.details)

"""News-only safety gate for XAUUSD. No FRED or macro-data dependency.

The verified USD economic calendar is the sole fundamental safety filter.
High-impact USD events block entries for two hours before and after release.
If the calendar cannot be verified, the gate fails closed and blocks entries.
"""
import json
import os
import time
import requests
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

CACHE_FILE = "news_calendar_cache.json"
CACHE_TTL_SECONDS = 900
EVENTS_SOURCE_OK = False
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

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

def _parse_event(item):
    date_str = str(item.get("date") or "").strip()
    time_str = str(item.get("time") or "").strip()
    if not date_str:
        return None
    if time_str and time_str.lower() not in ("all day", "tentative", ""):
        dt = None
        for fmt in ("%Y-%m-%d %I:%M%p", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        if dt is None:
            return None
    else:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt

def _read_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if time.time() - float(payload.get("saved_at", 0)) > CACHE_TTL_SECONDS:
            return None
        rows = payload.get("events")
        if not isinstance(rows, list):
            return None
        return rows
    except Exception:
        return None

def get_upcoming_events():
    """Return verified high/medium-impact USD events in the next 48 hours."""
    global EVENTS_SOURCE_OK
    cached = _read_cache()
    if cached is not None:
        EVENTS_SOURCE_OK = True
        now = datetime.now(timezone.utc)
        events = []
        for row in cached:
            try:
                dt = datetime.fromisoformat(row["datetime_utc"])
                hours = (dt - now).total_seconds() / 3600
                if -2 <= hours <= 48:
                    events.append(EconomicEvent(row["title"], dt, row["impact"],
                                                row["currency"], round(hours, 2)))
            except Exception:
                continue
        return sorted(events, key=lambda event: event.hours_until)

    EVENTS_SOURCE_OK = False
    response = requests.get(
        CALENDAR_URL,
        headers={"User-Agent": "Mozilla/5.0 DioMasteR-GOLD-AI"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise RuntimeError("USD news calendar returned an invalid response")

    now = datetime.now(timezone.utc)
    events = []
    cache_rows = []
    for item in data:
        if not isinstance(item, dict):
            continue
        currency = str(item.get("currency") or "").upper()
        impact = str(item.get("impact") or "").upper()
        if currency != "USD" or impact not in ("HIGH", "MEDIUM"):
            continue
        try:
            dt = _parse_event(item)
        except Exception:
            continue
        if dt is None:
            continue
        hours = (dt - now).total_seconds() / 3600
        if -2 <= hours <= 48:
            events.append(EconomicEvent(str(item.get("title") or "USD event"), dt,
                                        impact, currency, round(hours, 2)))
        cache_rows.append({
            "title": str(item.get("title") or "USD event"),
            "datetime_utc": dt.isoformat(),
            "impact": impact,
            "currency": currency,
        })

    # Only mark the source verified after a successful, structurally valid response.
    EVENTS_SOURCE_OK = True
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as handle:
            json.dump({"saved_at": time.time(), "events": cache_rows}, handle)
    except Exception:
        pass
    return sorted(events, key=lambda event: event.hours_until)

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
        details="News calendar verified; macro/FRED indicators intentionally disabled",
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

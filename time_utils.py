"""Awareness-time handling used by the countdown UI and D4 exports."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def awareness_datetime(case: dict) -> datetime | None:
    values = case.get("awareness", {})
    local_value = (values.get("local") or "").strip()
    timezone_name = (values.get("timezone") or "").strip()
    if not local_value or not timezone_name:
        return None
    try:
        local = datetime.fromisoformat(local_value)
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        return None
    if local.tzinfo is None:
        return local.replace(tzinfo=zone)
    return local.astimezone(zone)


def deadline_datetime(case: dict, hours: int) -> datetime | None:
    start = awareness_datetime(case)
    if start is None:
        return None
    from datetime import timezone
    return (start.astimezone(timezone.utc) + timedelta(hours=hours)).astimezone(start.tzinfo)


def deadline_iso(case: dict, hours: int) -> str:
    value = deadline_datetime(case, hours)
    return value.isoformat() if value else ""


def deadline_display(case: dict, hours: int) -> str:
    value = deadline_datetime(case, hours)
    return value.strftime("%Y-%m-%d %H:%M %Z") if value else ""


"""
Shared utility functions for sprint report tools.
"""

from datetime import date, timedelta


def parse_jira_time_to_hours(time_str: str) -> float:
    """
    Parse Jira time format (e.g., '1w 2d 4h 30m') to decimal hours.
    Jira conventions: 1w = 5d, 1d = 8h.
    """
    if not time_str or time_str.strip() in ("N/A", "0", "0m", "None"):
        return 0.0
    hours = 0.0
    for part in time_str.strip().split():
        if part.endswith("w"):
            hours += float(part[:-1]) * 40
        elif part.endswith("d"):
            hours += float(part[:-1]) * 8
        elif part.endswith("h"):
            hours += float(part[:-1])
        elif part.endswith("m"):
            hours += float(part[:-1]) / 60
        elif part.endswith("s"):
            hours += float(part[:-1]) / 3600
    return hours


def hours_to_jira(h: float) -> str:
    """Convert decimal hours back to Jira-style string (e.g., '1w 2d 4h 30m')."""
    if h <= 0:
        return "0h"
    h = round(h, 2)
    w = int(h // 40)
    h_rem = h - w * 40
    d = int(h_rem // 8)
    h_rem2 = h_rem - d * 8
    hrs = int(h_rem2)
    mins = int(round((h_rem2 - hrs) * 60))
    parts = []
    if w:
        parts.append(f"{w}w")
    if d:
        parts.append(f"{d}d")
    if hrs:
        parts.append(f"{hrs}h")
    if mins:
        parts.append(f"{mins}m")
    return " ".join(parts) if parts else "0h"


def working_days_in_range(start: date, end: date) -> int:
    """Count weekday (Mon-Fri) days from start to end, inclusive."""
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def working_dates_in_range(start: date, end: date) -> list[date]:
    """List all weekday dates from start to end, inclusive."""
    dates = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates


def seconds_to_hours(s: float) -> float:
    return s / 3600.0

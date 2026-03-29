"""Peak hours detection for Claude API usage."""

from __future__ import annotations

from datetime import UTC, datetime


def get_peak_status() -> dict:
    """Check whether current time is within Claude's peak usage window.

    Peak hours: weekdays 13:00-19:00 UTC (as of March 26, 2026).
    Weekends are always off-peak.

    Returns:
        Dict with is_peak, current_utc, window info, and time until next transition.
    """
    now = datetime.now(UTC)
    weekday = now.weekday()
    hour = now.hour
    minute = now.minute

    is_weekend = weekday >= 5
    is_peak_hours = 13 <= hour < 19
    is_peak = not is_weekend and is_peak_hours

    if is_peak:
        mins_left = (19 - hour - 1) * 60 + (60 - minute)
        next_transition = f"{mins_left // 60}h {mins_left % 60}m until off-peak"
    elif is_weekend:
        next_transition = "off-peak all weekend"
    elif hour < 13:
        mins_until = (13 - hour - 1) * 60 + (60 - minute)
        next_transition = f"{mins_until // 60}h {mins_until % 60}m until peak"
    else:
        next_transition = "off-peak until tomorrow 13:00 UTC"

    return {
        "is_peak": is_peak,
        "current_utc": now.strftime("%H:%M UTC"),
        "day": now.strftime("%A"),
        "peak_window": "13:00-19:00 UTC, weekdays only",
        "next_transition": next_transition,
    }

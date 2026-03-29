"""Tests for sylvan.services.peak - peak/off-peak hours detection."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch


class TestGetPeakStatus:
    def _call(self, fake_now: datetime) -> dict:
        with patch("sylvan.services.peak.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = datetime
            from sylvan.services.peak import get_peak_status

            return get_peak_status()

    def test_weekday_peak_hours(self):
        # Wednesday 15:30 UTC
        now = datetime(2026, 3, 25, 15, 30, tzinfo=UTC)
        result = self._call(now)
        assert result["is_peak"] is True
        assert "until off-peak" in result["next_transition"]
        assert result["day"] == "Wednesday"

    def test_weekday_before_peak(self):
        # Monday 10:00 UTC
        now = datetime(2026, 3, 23, 10, 0, tzinfo=UTC)
        result = self._call(now)
        assert result["is_peak"] is False
        assert "until peak" in result["next_transition"]

    def test_weekday_after_peak(self):
        # Tuesday 20:00 UTC
        now = datetime(2026, 3, 24, 20, 0, tzinfo=UTC)
        result = self._call(now)
        assert result["is_peak"] is False
        assert "until tomorrow" in result["next_transition"]

    def test_weekend_always_off_peak(self):
        # Saturday 15:00 UTC (would be peak on weekday)
        now = datetime(2026, 3, 28, 15, 0, tzinfo=UTC)
        result = self._call(now)
        assert result["is_peak"] is False
        assert "weekend" in result["next_transition"]

    def test_peak_boundary_start(self):
        # Exactly 13:00 UTC on weekday
        now = datetime(2026, 3, 25, 13, 0, tzinfo=UTC)
        result = self._call(now)
        assert result["is_peak"] is True

    def test_peak_boundary_end(self):
        # Exactly 19:00 UTC on weekday (should be off-peak, range is 13-19 exclusive)
        now = datetime(2026, 3, 25, 19, 0, tzinfo=UTC)
        result = self._call(now)
        assert result["is_peak"] is False

    def test_result_structure(self):
        now = datetime(2026, 3, 25, 14, 0, tzinfo=UTC)
        result = self._call(now)
        assert "is_peak" in result
        assert "current_utc" in result
        assert "day" in result
        assert "peak_window" in result
        assert "next_transition" in result
        assert result["peak_window"] == "13:00-19:00 UTC, weekdays only"

    def test_sunday_off_peak(self):
        # Sunday
        now = datetime(2026, 3, 29, 14, 0, tzinfo=UTC)
        result = self._call(now)
        assert result["is_peak"] is False
        assert "weekend" in result["next_transition"]

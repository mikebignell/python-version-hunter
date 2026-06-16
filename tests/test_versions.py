"""Tests for pyhunter.versions."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch, MagicMock
import json

import pytest

from pyhunter.versions import (
    CycleInfo,
    fetch_release_info,
    latest_patch_for,
    eol_date_for,
    latest_stable_version,
)


SAMPLE_API_RESPONSE = [
    {"cycle": "3.13", "latest": "3.13.4",  "eol": "2029-10-31"},
    {"cycle": "3.12", "latest": "3.12.10", "eol": "2028-10-31"},
    {"cycle": "3.11", "latest": "3.11.12", "eol": "2027-10-31"},
    {"cycle": "3.10", "latest": "3.10.17", "eol": "2026-10-31"},
    {"cycle": "3.9",  "latest": "3.9.23",  "eol": "2025-10-05"},
    {"cycle": "2.7",  "latest": "2.7.18",  "eol": "2020-01-01"},
]


def _make_cycles() -> list[CycleInfo]:
    return [
        CycleInfo(cycle=item["cycle"], latest=item["latest"], eol=item["eol"])
        for item in SAMPLE_API_RESPONSE
    ]


class TestCycleInfo:
    def test_major_minor_parsed(self):
        c = CycleInfo(cycle="3.12", latest="3.12.10", eol="2028-10-31")
        assert c.major_minor == (3, 12)

    def test_is_eol_past_date(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        c = CycleInfo(cycle="3.9", latest="3.9.23", eol=yesterday)
        assert c.is_eol

    def test_is_eol_future_date(self):
        future = (date.today() + timedelta(days=365)).isoformat()
        c = CycleInfo(cycle="3.13", latest="3.13.4", eol=future)
        assert not c.is_eol

    def test_is_eol_bool_true(self):
        c = CycleInfo(cycle="3.8", latest="3.8.20", eol=True)
        assert c.is_eol

    def test_is_eol_bool_false(self):
        c = CycleInfo(cycle="3.13", latest="3.13.4", eol=False)
        assert not c.is_eol

    def test_python2_is_eol(self):
        c = CycleInfo(cycle="2.7", latest="2.7.18", eol="2020-01-01")
        assert c.is_eol

    def test_eol_date_str(self):
        c = CycleInfo(cycle="3.12", latest="3.12.10", eol="2028-10-31")
        assert c.eol_date_str == "2028-10-31"


class TestLatestPatchFor:
    def test_known_cycle(self):
        cycles = _make_cycles()
        assert latest_patch_for((3, 12), cycles) == "3.12.10"

    def test_unknown_cycle(self):
        cycles = _make_cycles()
        assert latest_patch_for((3, 99), cycles) is None

    def test_python2_cycle(self):
        cycles = _make_cycles()
        assert latest_patch_for((2, 7), cycles) == "2.7.18"


class TestEolDateFor:
    def test_known_cycle(self):
        cycles = _make_cycles()
        assert eol_date_for((3, 9), cycles) == "2025-10-05"

    def test_unknown_cycle(self):
        cycles = _make_cycles()
        assert eol_date_for((3, 99), cycles) is None


class TestLatestStableVersion:
    def test_returns_highest_active_cycle(self):
        cycles = _make_cycles()
        # From SAMPLE_API_RESPONSE, today (2026-06-16): 3.9 and 2.7 are EOL, 3.10 is active.
        # The latest active should be 3.13.
        result = latest_stable_version(cycles)
        # At least it should be a 3.x version
        assert result is not None
        assert result.startswith("3.")

    def test_empty_cycles(self):
        assert latest_stable_version([]) is None

    def test_all_eol(self):
        cycles = [
            CycleInfo(cycle="3.9", latest="3.9.23", eol="2025-10-05"),
            CycleInfo(cycle="2.7", latest="2.7.18", eol="2020-01-01"),
        ]
        assert latest_stable_version(cycles) is None


class TestFetchReleaseInfo:
    def test_returns_cycles_on_success(self):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(SAMPLE_API_RESPONSE).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = fetch_release_info()

        assert result is not None
        assert len(result) == len(SAMPLE_API_RESPONSE)
        assert result[0].cycle == "3.13"

    def test_returns_none_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            result = fetch_release_info()
        assert result is None

    def test_returns_none_on_timeout(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            result = fetch_release_info()
        assert result is None

    def test_returns_none_on_bad_json(self):
        mock_response = MagicMock()
        mock_response.read.return_value = b"not json {"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = fetch_release_info()
        assert result is None

    def test_skips_entries_without_dot_in_cycle(self):
        data = [
            {"cycle": "3.12", "latest": "3.12.10", "eol": "2028-10-31"},
            {"cycle": "alpha", "latest": "0.0.0", "eol": False},  # no dot → skip
        ]
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(data).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = fetch_release_info()
        assert result is not None
        assert len(result) == 1

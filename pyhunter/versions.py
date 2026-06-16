"""Fetch latest Python release data from endoflife.date."""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Optional

ENDOFLIFE_URL = "https://endoflife.date/api/python.json"
_TIMEOUT = 6


@dataclass
class CycleInfo:
    cycle: str    # "3.12"
    latest: str   # "3.12.10"
    eol: str | bool  # ISO date string or False if still active

    @property
    def major_minor(self) -> tuple[int, int]:
        a, b = self.cycle.split(".")
        return (int(a), int(b))

    @property
    def is_eol(self) -> bool:
        if isinstance(self.eol, bool):
            return self.eol
        try:
            return date.today() >= date.fromisoformat(self.eol)
        except ValueError:
            return False

    @property
    def eol_date_str(self) -> str:
        if isinstance(self.eol, bool):
            return "unknown"
        return self.eol


def fetch_release_info(timeout: int = _TIMEOUT) -> Optional[list[CycleInfo]]:
    """
    Fetch Python cycle data from endoflife.date.
    Returns None on any network or parse failure so callers degrade gracefully.
    """
    try:
        req = urllib.request.Request(
            ENDOFLIFE_URL,
            headers={
                "User-Agent": "pyhunter/1.0 (github.com/mikebignell/python-version-hunter)"
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read())
        return [
            CycleInfo(cycle=item["cycle"], latest=item["latest"], eol=item["eol"])
            for item in raw
            if "cycle" in item and "latest" in item and "." in item.get("cycle", "")
        ]
    except Exception:
        return None


def latest_patch_for(
    major_minor: tuple[int, int], cycles: list[CycleInfo]
) -> Optional[str]:
    for c in cycles:
        if c.major_minor == major_minor:
            return c.latest
    return None


def eol_date_for(
    major_minor: tuple[int, int], cycles: list[CycleInfo]
) -> Optional[str]:
    for c in cycles:
        if c.major_minor == major_minor:
            return c.eol_date_str
    return None


def latest_stable_version(cycles: list[CycleInfo]) -> Optional[str]:
    """Return the latest patch of the newest non-EOL Python 3 cycle."""
    active = [c for c in cycles if not c.is_eol and c.major_minor[0] == 3]
    if not active:
        return None
    active.sort(key=lambda c: c.major_minor, reverse=True)
    return active[0].latest

"""Bridge the Claude Code status line to the local dashboard."""

import json
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from usage import Window

CACHE = Path.home() / "Library/Caches/35inchSmartScreen/claude-usage.json"
PERIODS = {"five_hour": 300, "seven_day": 10080}


@dataclass(frozen=True)
class ClaudeUsage:
    received_at: datetime
    windows: tuple[Window, ...]


def parse_limits(payload):
    limits = payload.get("rate_limits") if isinstance(payload, dict) else None
    if not isinstance(limits, dict):
        return {}
    valid = {}
    for name in PERIODS:
        window = limits.get(name)
        if not isinstance(window, dict):
            continue
        used, reset = window.get("used_percentage"), window.get("resets_at")
        if type(used) not in (int, float) or not 0 <= used <= 100:
            continue
        if type(reset) is not int or reset <= 0:
            continue
        valid[name] = {"used_percentage": used, "resets_at": reset}
    return valid


def write_usage(payload, path=CACHE):
    limits = parse_limits(payload)
    if not limits:
        return {}
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump({"received_at": time.time(), "rate_limits": limits}, stream)
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return limits


def read_usage(path=CACHE):
    try:
        payload = json.loads(path.read_text())
        limits = parse_limits(payload)
        if not limits:
            return None
        received_at = datetime.fromtimestamp(payload["received_at"]).astimezone()
        windows = tuple(
            Window(round(window["used_percentage"]), PERIODS[name], window["resets_at"])
            for name, window in limits.items()
        )
        return ClaudeUsage(received_at, windows)
    except (OSError, OverflowError, ValueError, KeyError, TypeError):
        return None


def main():
    try:
        limits = write_usage(json.load(sys.stdin))
    except (OSError, ValueError):
        return 1

    if limits:
        labels = {"five_hour": "5h", "seven_day": "7d"}
        parts = [
            f"{labels[name]} {window['used_percentage']:g}% used"
            for name, window in limits.items()
        ]
        print("Claude · " + " · ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

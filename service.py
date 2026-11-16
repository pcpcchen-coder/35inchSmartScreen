"""Install or remove the per-user macOS LaunchAgent."""

import argparse
import json
import os
import plistlib
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from claude_usage import write_usage
from preferences import CHOICES, read_preferences, set_preference
from usage import find_codex

LABEL = "com.pcpcchen.35inchsmartscreen"
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
LOG = Path.home() / "Library/Logs/35inchSmartScreen/dashboard.log"
ROOT = Path(__file__).resolve().parent
DOMAIN = f"gui/{os.getuid()}"
TARGET = f"{DOMAIN}/{LABEL}"


def launchctl(*args, quiet=False, check=True):
    return subprocess.run(
        ["/bin/launchctl", *args], check=check,
        capture_output=quiet,
    )


def bootstrap(plist):
    # launchd can still be tearing down the previous job after bootout returns.
    for attempt in range(6):
        result = launchctl("bootstrap", DOMAIN, str(plist), quiet=True, check=False)
        if result.returncode == 0:
            return 0
        if result.returncode != 5 or attempt == 5:
            sys.stderr.buffer.write(result.stderr)
            return result.returncode
        time.sleep(1)


def loaded():
    return launchctl("print", TARGET, quiet=True, check=False).returncode == 0


def unload():
    if loaded():
        launchctl("bootout", TARGET)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=(
        "install", "status", "uninstall", "menu-status", "set", "refresh", "import-claude",
    ))
    parser.add_argument("--dashboard-root", type=Path, default=ROOT)
    parser.add_argument("--dashboard-python", default=sys.executable)
    parser.add_argument("setting", nargs="?", choices=CHOICES)
    parser.add_argument("value", nargs="?")
    args = parser.parse_args()

    if args.action == "menu-status":
        print(json.dumps({"enabled": PLIST.is_file() and loaded(), **asdict(read_preferences())}))
        return 0
    if args.action == "set":
        if args.setting is None or args.value is None:
            parser.error("set requires a setting and value")
        try:
            set_preference(args.setting, args.value)
        except ValueError as error:
            parser.error(str(error))
        return 0
    if args.action == "import-claude":
        try:
            if write_usage(json.load(sys.stdin), source="desktop"):
                return 0
        except (OSError, ValueError) as error:
            parser.error(str(error))
        parser.error("No valid Claude usage fields were supplied")
    if args.action == "refresh":
        return launchctl("kill", "SIGUSR1", TARGET, check=False).returncode

    if args.action == "status":
        return launchctl("print", TARGET, check=False).returncode
    if args.action == "uninstall":
        unload()
        PLIST.unlink(missing_ok=True)
        return 0

    codex = find_codex()
    if not codex:
        parser.error("Codex executable unavailable. Add it to PATH and try again.")
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "Label": LABEL,
        "ProgramArguments": [
            args.dashboard_python, str(args.dashboard_root / "dashboard.py"), "--codex", codex,
        ],
        "WorkingDirectory": str(args.dashboard_root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardErrorPath": str(LOG),
    }
    data = plistlib.dumps(config)
    if PLIST.exists() and PLIST.read_bytes() == data and loaded():
        launchctl("kickstart", "-k", TARGET)
    else:
        unload()
        temporary = PLIST.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(PLIST)
        launchctl("enable", TARGET)
        result = bootstrap(PLIST)
        if result:
            return result
    print(f"Dashboard service started. Log at {LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

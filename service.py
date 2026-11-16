"""Install or remove the per-user macOS LaunchAgent."""

import argparse
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

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


def loaded():
    return launchctl("print", TARGET, quiet=True, check=False).returncode == 0


def unload():
    if loaded():
        launchctl("bootout", TARGET)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "uninstall"))
    args = parser.parse_args()

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
        "ProgramArguments": [sys.executable, str(ROOT / "dashboard.py"), "--codex", codex],
        "WorkingDirectory": str(ROOT),
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
        # launchd can still be tearing down the previous job after bootout returns.
        for attempt in range(6):
            result = launchctl("bootstrap", DOMAIN, str(PLIST), quiet=True, check=False)
            if result.returncode == 0:
                break
            if result.returncode != 5 or attempt == 5:
                sys.stderr.buffer.write(result.stderr)
                return result.returncode
            time.sleep(1)
    print(f"Dashboard service started. Log at {LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

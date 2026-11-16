"""Build and install the SmartScreen menu bar app for the current user."""

import argparse
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from service import DOMAIN, LOG, ROOT, bootstrap, launchctl

LABEL = "com.pcpcchen.35inchsmartscreen.menu"
APP = Path.home() / "Applications/SmartScreen.app"
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
TARGET = f"{DOMAIN}/{LABEL}"
EXECUTABLE = "Contents/MacOS/SmartScreen"


def unload():
    if launchctl("print", TARGET, quiet=True, check=False).returncode == 0:
        launchctl("bootout", TARGET)


def build(bundle):
    executable = bundle / EXECUTABLE
    executable.parent.mkdir(parents=True)
    resources = bundle / "Contents/Resources"
    resources.mkdir()
    for name in ("service.py", "preferences.py", "usage.py"):
        shutil.copy2(ROOT / name, resources / name)
    (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": LABEL,
        "CFBundleName": "SmartScreen",
        "CFBundleDisplayName": "SmartScreen",
        "CFBundleExecutable": executable.name,
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1",
        "CFBundleShortVersionString": "1.0",
        "LSUIElement": True,
        "SmartScreenRoot": str(ROOT),
        "SmartScreenPython": str(Path(sys.executable).resolve()),
        "SmartScreenDashboardPython": sys.executable,
    }))
    subprocess.run(["/usr/bin/xcrun", "swiftc", "-O", "-framework", "AppKit",
                    str(ROOT / "macos/SmartScreenMenu.swift"), "-o", str(executable)], check=True)
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(bundle)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall"))
    args = parser.parse_args()

    if APP.is_symlink():
        parser.error(f"Cannot replace the symbolic link at {APP}")
    if APP.exists():
        try:
            owner = plistlib.loads((APP / "Contents/Info.plist").read_bytes()).get("CFBundleIdentifier")
        except (OSError, ValueError, plistlib.InvalidFileException):
            owner = None
        if owner != LABEL:
            parser.error(f"A different app is already installed at {APP}")

    if args.action == "uninstall":
        unload()
        PLIST.unlink(missing_ok=True)
        if APP.exists():
            shutil.rmtree(APP)
        return 0

    APP.parent.mkdir(parents=True, exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=APP.parent) as root:
        staging = Path(root) / APP.name
        backup = Path(root) / "previous.app"
        build(staging)
        unload()
        if APP.exists():
            APP.rename(backup)
        try:
            staging.rename(APP)
        except OSError:
            if backup.exists():
                backup.rename(APP)
            raise

    temporary = PLIST.with_suffix(".tmp")
    temporary.write_bytes(plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [str(APP / EXECUTABLE)],
        "RunAtLoad": True,
        "LimitLoadToSessionType": "Aqua",
        "StandardErrorPath": str(LOG.with_name("menu.log")),
    }))
    temporary.replace(PLIST)
    launchctl("enable", TARGET)
    result = bootstrap(PLIST)
    if result == 0:
        print(f"SmartScreen menu installed at {APP}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())

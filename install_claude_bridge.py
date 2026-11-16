"""Register the optional SmartScreen Native Messaging host for Chrome."""

import argparse
import base64
import hashlib
import json
import shlex
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = "com.pcpcchen.smartscreen_claude"
SUPPORT = Path.home() / "Library/Application Support"
DEST = SUPPORT / "35inchSmartScreen/ChromeBridge"
MANIFEST = SUPPORT / "Google/Chrome/NativeMessagingHosts" / f"{HOST}.json"


def extension_origin():
    manifest = json.loads((ROOT / "chrome-claude/manifest.json").read_text())
    digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
    extension_id = digest.translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop"))
    return f"chrome-extension://{extension_id}/"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall"))
    args = parser.parse_args()
    if args.action == "uninstall":
        MANIFEST.unlink(missing_ok=True)
        return 0

    DEST.mkdir(parents=True, exist_ok=True)
    for name in ("claude_native_host.py", "claude_usage.py", "usage.py"):
        shutil.copy2(ROOT / name, DEST / name)
    launcher = DEST / "claude-native-host"
    command = shlex.join([str(Path(sys.executable).resolve()), "-B", str(DEST / "claude_native_host.py")])
    launcher.write_text(f"#!/bin/sh\nexec {command}\n")
    launcher.chmod(0o700)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    temporary = MANIFEST.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "name": HOST,
        "description": "Import Claude quota percentages into SmartScreen",
        "path": str(launcher),
        "type": "stdio",
        "allowed_origins": [extension_origin()],
    }, indent=2) + "\n")
    temporary.replace(MANIFEST)
    print("Registered the SmartScreen host for the Chrome extension.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

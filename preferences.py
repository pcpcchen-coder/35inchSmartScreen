"""Local preferences shared by the dashboard and the menu bar."""

import json
from dataclasses import dataclass, fields, replace
from pathlib import Path
from tempfile import NamedTemporaryFile

PREFERENCES = Path.home() / "Library/Application Support/35inchSmartScreen/preferences.json"
CHOICES = {
    "mode": ("combined", "chatgpt", "claude"),
    "poll_seconds": (15, 30, 60, 120),
    "brightness": (20, 40, 60, 80, 100),
    "blank_on_stop": (False, True),
}


@dataclass(frozen=True)
class Preferences:
    mode: str = "combined"
    poll_seconds: int = 30
    brightness: int | None = None
    blank_on_stop: bool = False


def read_preferences(path=PREFERENCES):
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return Preferences()

    if not isinstance(raw, dict):
        return Preferences()
    values = {}
    for field in fields(Preferences):
        value = raw.get(field.name)
        if any(type(value) is type(choice) and value == choice for choice in CHOICES[field.name]):
            values[field.name] = value
    return Preferences(**values)


def set_preference(key, value, path=PREFERENCES):
    for choice in CHOICES[key]:
        if str(choice).lower() == value:
            updated = replace(read_preferences(path), **{key: choice})
            break
    else:
        raise ValueError(f"Unsupported value for {key}: {value}")

    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump({field.name: getattr(updated, field.name) for field in fields(updated)}, stream)
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

"""Local preferences shared by the dashboard and the menu bar."""

import json
from dataclasses import asdict, dataclass, replace
from datetime import date
from ipaddress import ip_address
from pathlib import Path
from tempfile import NamedTemporaryFile

PREFERENCES = Path.home() / "Library/Application Support/35inchSmartScreen/preferences.json"
CHOICES = {
    "mode": ("combined", "chatgpt", "claude"),
    "poll_seconds": (15, 30, 60, 120),
    "brightness": (20, 40, 60, 80, 100),
    "blank_on_stop": (False, True),
}


SUBSCRIPTION_FIELDS = {"chatgpt": "chatgpt_subscription", "claude": "claude_subscription"}
SUBSCRIPTION_EVENTS = ("renews", "ends")


@dataclass(frozen=True)
class Subscription:
    event: str
    date: str


@dataclass(frozen=True)
class Preferences:
    mode: str = "combined"
    poll_seconds: int = 30
    brightness: int | None = None
    blank_on_stop: bool = False
    chatgpt_subscription: Subscription | None = None
    claude_subscription: Subscription | None = None
    nous_core_port: int | None = None
    pi_host: str | None = None


def read_preferences(path=PREFERENCES):
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return Preferences()

    if not isinstance(raw, dict):
        return Preferences()
    values = {}
    for field, options in CHOICES.items():
        value = raw.get(field)
        if any(type(value) is type(choice) and value == choice for choice in options):
            values[field] = value
    for field in SUBSCRIPTION_FIELDS.values():
        entry = raw.get(field)
        if isinstance(entry, dict):
            try:
                values[field] = subscription(entry.get("event"), entry.get("date"))
            except ValueError:
                pass
    try:
        values.update(monitor_values(raw.get("nous_core_port"), raw.get("pi_host")))
    except ValueError:
        pass
    return Preferences(**values)


def monitor_values(nous_port, pi_host):
    if nous_port is not None and (type(nous_port) is not int or not 1 <= nous_port <= 65535):
        raise ValueError("Use a valid localhost port for Nous Core")
    if pi_host is not None:
        if not isinstance(pi_host, str):
            raise ValueError("Use a local IP address for the Pi")
        address = ip_address(pi_host)
        if not (address.is_private and not address.is_loopback and not address.is_unspecified):
            raise ValueError("Use a local network IP address for the Pi")
        pi_host = str(address)
    return {"nous_core_port": nous_port, "pi_host": pi_host}


def set_monitors(nous_port, pi_host, path=PREFERENCES):
    updated = replace(read_preferences(path), **monitor_values(nous_port, pi_host))
    save_preferences(updated, path)


def set_preference(key, value, path=PREFERENCES):
    for choice in CHOICES[key]:
        if str(choice).lower() == value:
            updated = replace(read_preferences(path), **{key: choice})
            break
    else:
        raise ValueError(f"Unsupported value for {key}: {value}")

    save_preferences(updated, path)


def subscription(event, day):
    try:
        normalized = date.fromisoformat(day).isoformat()
    except (TypeError, ValueError):
        raise ValueError("Use YYYY-MM-DD for the subscription date") from None
    if normalized != day or event not in SUBSCRIPTION_EVENTS:
        raise ValueError("Use a renewal or end date in YYYY-MM-DD format")
    return Subscription(event, normalized)


def set_subscription(provider, event, day=None, path=PREFERENCES):
    value = None if event == "clear" else subscription(event, day)
    updated = replace(read_preferences(path), **{SUBSCRIPTION_FIELDS[provider]: value})
    save_preferences(updated, path)


def save_preferences(preferences, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(asdict(preferences), stream)
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

#!/usr/bin/env python3
"""Live ChatGPT and Claude usage dashboard for a TURZX 3.5-inch screen."""

import argparse
import logging
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from claude_usage import ClaudeUsage, read_usage
from monitor_status import Reachability
from preferences import Preferences, Subscription, read_preferences
from turzx import HEIGHT, WIDTH, Display
from usage import CodexServer, UsageError, Window, find_codex, quota_windows

BG = "#10181A"
PANEL = "#192528"
BORDER = "#304345"
TEXT = "#F0F7F5"
MUTED = "#A7BFBD"
TEAL = "#64E2C1"
SKY = "#8EBDFF"
AMBER = "#FFD17F"
RED = "#FF9C8F"
CLAUDE = "#F5A987"
FONT_DIR = Path("/System/Library/Fonts")


@dataclass
class Snapshot:
    windows: tuple[Window, ...] | None = None
    limits_at: datetime | None = None
    failed: bool = False

    def refresh(self, server):
        try:
            windows = quota_windows(server.call("account/rateLimits/read"))
        except (UsageError, KeyError, TypeError, ValueError):
            if not self.failed:
                logging.warning("Could not refresh ChatGPT limits")
            self.failed = True
        else:
            if self.limits_at is None or self.failed:
                logging.info("ChatGPT limits received")
            self.windows = windows
            self.limits_at = datetime.now().astimezone()
            self.failed = False


@lru_cache
def font(size, face):
    name, index = {
        "regular": ("HelveticaNeue.ttc", 0),
        "bold": ("HelveticaNeue.ttc", 1),
        "mono": ("Menlo.ttc", 0),
    }[face]
    return ImageFont.truetype(str(FONT_DIR / name), size, index=index)


def label(draw, xy, value, size, color=TEXT, face="regular", anchor="lt"):
    draw.text(xy, value, fill=color, font=font(size, face), anchor=anchor)


def panel(draw, top, height):
    draw.rounded_rectangle((14, top, 305, top + height - 1), radius=15,
                           fill=PANEL, outline=BORDER)


def window_name(minutes):
    names = {300: "5-HOUR", 1440: "DAILY", 10080: "WEEKLY",
             43200: "MONTHLY"}
    if minutes in names:
        return names[minutes]
    if minutes is None:
        return "USAGE"
    if minutes % 1440 == 0:
        return f"{minutes // 1440}-DAY"
    if minutes % 60 == 0:
        return f"{minutes // 60}-HOUR"
    return f"{minutes}-MIN"


def reset_label(reset_at, now):
    if reset_at is None:
        return "Reset unknown"
    seconds = reset_at - int(now.timestamp())
    if seconds <= 0:
        return "Reset pending"
    minutes = (seconds + 59) // 60
    if minutes >= 1440:
        return f"Reset {minutes // 1440}d {minutes % 1440 // 60}h"
    if minutes >= 60:
        return f"Reset {minutes // 60}h {minutes % 60:02}m"
    return f"Reset {minutes}m"


def allowance(window, accent):
    remaining = max(0, min(100, 100 - window.used))
    color = RED if remaining <= 10 else AMBER if remaining <= 25 else accent
    return remaining, color


def chat_status(snapshot):
    if snapshot.failed:
        return ("STALE" if snapshot.limits_at else "OFFLINE", AMBER)
    return "LIVE", TEAL


def claude_status(usage, now):
    if usage is None:
        return "WAITING", MUTED
    if any(quota_expired(window, now) for window in usage.windows):
        return "UPDATE DUE", AMBER
    age = now - usage.received_at
    if usage.source == "web":
        return ("STALE", AMBER) if age > timedelta(minutes=3) else ("LIVE", CLAUDE)
    cached = age > timedelta(minutes=15)
    if usage.source == "desktop":
        return "SNAPSHOT", AMBER if cached else CLAUDE
    return ("CACHED", AMBER) if cached else ("RECENT", CLAUDE)


def quota_expired(window, now):
    return window.reset_at is not None and window.reset_at <= now.timestamp()


def session_not_started(window):
    if window.idle is not None:
        return window.idle
    return window.reset_at is None and window.minutes == 300 and window.used == 0


def quota_card(draw, box, window, now, accent):
    left, top = box[:2]
    draw.rounded_rectangle(box, radius=13, fill=PANEL, outline=BORDER)
    label(draw, (left + 12, top + 11), f"{window_name(window.minutes)} LEFT", 13, MUTED, "bold")
    if quota_expired(window, now):
        label(draw, (left + 11, top + 33), "–", 46, MUTED, "bold")
        label(draw, (left + 12, top + 80), "Awaiting update", 16, MUTED)
        return

    remaining, color = allowance(window, accent)
    label(draw, (left + 11, top + 31), f"{remaining}%", 46, color, "bold")
    reset = "On first use" if session_not_started(window) else reset_label(window.reset_at, now)
    label(draw, (left + 12, top + 80), reset, 16, TEXT)


def subscription_label(subscription, now):
    if subscription is None:
        return "DATE NOT SET", MUTED
    past = subscription.date < now.date().isoformat()
    if subscription.event == "ends":
        return "ENDS", AMBER
    if past:
        return "RENEWAL", AMBER
    return "RENEWS", MUTED


def provider_section(draw, top, title, accent, status, stamp, subscription, windows, now,
                     *, empty, stacked=False):
    label(draw, (16, top), title, 31, accent, "bold")
    subscription_text, date_color = subscription_label(subscription, now)
    label(draw, (16, top + 43), subscription_text, 15, date_color, "bold")
    day = subscription.date if subscription else "—"
    label(draw, (16, top + 64), day, 24, TEXT, "mono")

    text, color = status
    if stamp is not None and stamp.date() != now.date():
        text += stamp.strftime(" · %m/%d")
    label(draw, (304, top + 43), text, 16, color, "bold", "rt")
    time_text = stamp.strftime("%H:%M:%S") if stamp else "—"
    label(draw, (304, top + 64), time_text, 24, TEXT, "mono", "rt")

    card_top = top + 99
    if not windows:
        panel(draw, card_top, 104)
        label(draw, (27, card_top + 45), empty, 18)
        return

    if stacked:
        spans = ((14, 305, card_top), (14, 305, card_top + 140))
    elif len(windows) == 1:
        spans = ((14, 305, card_top),)
    else:
        spans = ((14, 155, card_top), (165, 305, card_top))
    for window, (left, right, y) in zip(windows, spans):
        quota_card(draw, (left, y, right, y + 103), window, now, accent)


def status_messages(snapshot, claude, now, mode, unreachable):
    messages = []
    if mode != "claude" and snapshot.failed:
        messages.append("ChatGPT sync unavailable")
    if mode != "chatgpt":
        status, _ = claude_status(claude, now)
        if status == "WAITING":
            messages.append("Claude usage not connected")
        elif status in {"STALE", "CACHED"}:
            messages.append("Claude sync delayed")
        elif status == "UPDATE DUE":
            messages.append("Claude quota reset · awaiting data")
        elif claude.source == "desktop" and now - claude.received_at > timedelta(minutes=15):
            messages.append("Claude snapshot needs refresh")
        elif any(window.reset_at is None and not session_not_started(window) for window in claude.windows):
            messages.append("Claude reset time unavailable")

    providers = (
        ("ChatGPT", snapshot.windows if mode != "claude" and not snapshot.failed else ()),
        ("Claude", claude.windows if claude and mode != "chatgpt" else ()),
    )
    for name, windows in providers:
        remaining = min((max(0, 100 - window.used) for window in windows or ()
                         if not quota_expired(window, now)), default=100)
        if remaining <= 10:
            messages.append(f"{name} {remaining}% left")
    messages.extend(f"{name} unreachable" for name in unreachable)
    return messages


def status_strip(draw, messages):
    if not messages:
        return
    draw.rounded_rectangle((14, 450, 305, 473), radius=7, fill=PANEL, outline=BORDER)
    draw.ellipse((23, 459, 28, 464), fill=AMBER)
    for count in range(len(messages), 0, -1):
        text = "  ·  ".join(messages[:count])
        if count < len(messages):
            text += f"  +{len(messages) - count}"
        if font(13, "bold").getlength(text) <= 265:
            label(draw, (35, 456), text, 13, AMBER, "bold")
            break


def render_dashboard(snapshot, claude, now, preferences, demo=False, *, unreachable=()):
    mode = preferences.mode
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH - 1, 3), fill=CLAUDE if mode == "claude" else TEAL)
    if mode == "combined":
        draw.rectangle((160, 0, WIDTH - 1, 3), fill=CLAUDE)
        draw.line((15, 229, 305, 229), fill=BORDER)
    if demo:
        label(draw, (304, 20), "DEMO", 13, MUTED, "bold", "rt")

    if mode != "claude":
        empty = "Quota unavailable" if snapshot.windows is None else "No quota window reported"
        provider_section(draw, 18, "ChatGPT", TEAL, chat_status(snapshot), snapshot.limits_at,
                         preferences.chatgpt_subscription, snapshot.windows, now,
                         empty=empty, stacked=mode == "chatgpt")
    if mode != "chatgpt":
        top = 241 if mode == "combined" else 18
        provider_section(draw, top, "Claude", CLAUDE, claude_status(claude, now),
                         claude.received_at if claude else None, preferences.claude_subscription,
                         claude.windows if claude else None, now, empty="Import Claude App usage",
                         stacked=mode == "claude")
    status_strip(draw, status_messages(snapshot, claude, now, mode, unreachable))
    return image


def demo_image(path, mode):
    now = datetime.fromisoformat("2026-11-16T19:24:30+08:00")
    claude = ClaudeUsage(now - timedelta(minutes=7), (
        Window(0, 300, None),
        Window(54, 10080, int(now.timestamp()) + 259200),
    ), "desktop")
    snapshot = Snapshot((
        Window(25, 300, int(now.timestamp()) + 8650),
        Window(59, 10080, int(now.timestamp()) + 189000),
    ), now)
    prefs = Preferences(mode=mode, chatgpt_subscription=Subscription("renews", "2026-12-16"),
                        claude_subscription=Subscription("ends", "2026-12-05"))
    render_dashboard(snapshot, claude, now, prefs, demo=True,
                     unreachable=("Pi",) if mode == "combined" else ()).save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, help="override the saved usage polling interval (default 30)")
    parser.add_argument("--codex", help="path to the Codex executable")
    parser.add_argument("--port", help="USB device selector by serial path (default: autodetect)")
    parser.add_argument("--once", action="store_true", help="fetch and write one hardware frame")
    preview = parser.add_mutually_exclusive_group()
    preview.add_argument("--preview", type=Path, help="save a ChatGPT demo PNG")
    preview.add_argument("--preview-claude", type=Path, help="save a Claude demo PNG")
    preview.add_argument("--preview-combined", type=Path, help="save a combined demo PNG")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    for path, mode in ((args.preview, "chatgpt"), (args.preview_claude, "claude"),
                       (args.preview_combined, "combined")):
        if path:
            demo_image(path, mode)
            return 0
    if args.interval is not None and args.interval < 10:
        parser.error("--interval must be at least 10 seconds")
    executable = args.codex or find_codex()
    if not executable:
        parser.error("Codex executable unavailable. Specify --codex.")

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    server = CodexServer(executable)
    screen = Display(args.port)
    snapshot = Snapshot()
    reachability = Reachability()
    last_poll = None
    last_claude_snapshot = None
    preferences = read_preferences()
    usb_offline = None
    stopping = False
    refresh_requested = False

    def request_refresh(_signum, _frame):
        nonlocal refresh_requested
        refresh_requested = True

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGUSR1, request_refresh)
    try:
        while not stopping:
            preferences = read_preferences()
            mode = preferences.mode
            interval = args.interval or preferences.poll_seconds
            poll_due = last_poll is None or time.monotonic() >= last_poll + interval
            if mode != "claude" and (refresh_requested or poll_due):
                if refresh_requested:
                    logging.info("Manual ChatGPT sync requested")
                    refresh_requested = False
                snapshot.refresh(server)
                last_poll = time.monotonic()
                if stopping:
                    break

            now = datetime.now().astimezone()
            claude = read_usage() if mode != "chatgpt" else None
            reachability.refresh(preferences)
            frame = render_dashboard(snapshot, claude, now, preferences, unreachable=reachability.unreachable)
            try:
                screen.show(frame, brightness=preferences.brightness)
            except OSError as error:
                if usb_offline is not True or args.once:
                    logging.warning("USB display unavailable: %s", error)
                screen.close()
                usb_offline = True
            else:
                if usb_offline is not False:
                    logging.info("Dashboard frame sent to USB display (%s)", mode)
                usb_offline = False
                if claude and claude.received_at != last_claude_snapshot:
                    logging.info("Claude usage displayed (%s)", claude.source)
                    last_claude_snapshot = claude.received_at
            if args.once:
                return int(usb_offline or snapshot.failed)
            if not stopping:
                time.sleep(2)
    finally:
        try:
            if stopping and preferences.blank_on_stop:
                screen.power_off()
        except OSError as error:
            logging.warning("Could not turn off the USB display: %s", error)
        finally:
            screen.close()
            server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

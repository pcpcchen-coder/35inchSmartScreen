#!/usr/bin/env python3
"""Live ChatGPT usage dashboard for a TURZX 3.5-inch screen."""

import argparse
import logging
import signal
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from claude_usage import ClaudeUsage, read_usage
from preferences import read_preferences
from turzx import HEIGHT, WIDTH, Display
from usage import CodexServer, UsageError, Window, daily_tokens, find_codex, quota_windows

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
    tokens: dict = field(default_factory=dict)
    limits_at: datetime | None = None
    tokens_at: datetime | None = None
    errors: set[str] = field(default_factory=set)

    def refresh(self, server):
        for name, method, transform, data_attr, time_attr in (
            ("limits", "account/rateLimits/read", quota_windows, "windows", "limits_at"),
            ("tokens", "account/usage/read", daily_tokens, "tokens", "tokens_at"),
        ):
            try:
                data = transform(server.call(method))
            except (UsageError, KeyError, TypeError, ValueError):
                if name not in self.errors:
                    logging.warning("Could not refresh %s", name)
                self.errors.add(name)
            else:
                if getattr(self, time_attr) is None or name in self.errors:
                    logging.info("%s data received", name.capitalize())
                setattr(self, data_attr, data)
                setattr(self, time_attr, datetime.now().astimezone())
                self.errors.discard(name)
        logging.debug("Usage refresh finished")


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
    names = {300: "5-HOUR WINDOW", 1440: "DAILY WINDOW", 10080: "WEEKLY WINDOW",
             43200: "MONTHLY WINDOW"}
    if minutes in names:
        return names[minutes]
    if minutes is None:
        return "USAGE WINDOW"
    if minutes % 1440 == 0:
        return f"{minutes // 1440}-DAY WINDOW"
    if minutes % 60 == 0:
        return f"{minutes // 60}-HOUR WINDOW"
    return f"{minutes}-MIN WINDOW"


def reset_label(reset_at, now):
    if reset_at is None:
        return "Reset time unavailable"
    seconds = reset_at - int(now.timestamp())
    if seconds <= 0:
        return "Reset pending"
    minutes = (seconds + 59) // 60
    if minutes >= 1440:
        return f"Resets in {minutes // 1440}d {minutes % 1440 // 60}h"
    if minutes >= 60:
        return f"Resets in {minutes // 60}h {minutes % 60:02}m"
    return f"Resets in {minutes}m"


def quota_card(draw, top, window, now, base_color):
    panel(draw, top, 102)
    remaining = max(0, min(100, 100 - window.used))
    color = RED if remaining <= 10 else AMBER if remaining <= 25 else base_color
    label(draw, (27, top + 12), window_name(window.minutes), 13, MUTED, "bold")
    label(draw, (26, top + 28), f"{remaining}%", 43, color, "bold")
    label(draw, (292, top + 37), "LEFT", 13, color, "bold", "rt")
    label(draw, (292, top + 56), reset_label(window.reset_at, now), 14, TEXT, anchor="rt")
    draw.rounded_rectangle((27, top + 80, 292, top + 88), radius=4, fill=BORDER)
    if remaining:
        draw.rounded_rectangle((27, top + 80, 27 + round(265 * remaining / 100), top + 88),
                               radius=4, fill=color)


def compact(value):
    for divisor, suffix in ((10**12, "T"), (10**9, "B"), (10**6, "M"), (10**3, "K")):
        if value >= divisor:
            return f"{value / divisor:.1f}{suffix}"
    return str(value)


def token_chart(draw, top, snapshot, now):
    bottom = 431
    panel(draw, top, bottom - top + 1)
    label(draw, (27, top + 12), "TOKENS / 7 DAYS", 13, MUTED, "bold")
    if snapshot.tokens_at is None:
        label(draw, (27, top + 39), "Token history unavailable", 18)
        return

    end = now.astimezone(UTC).date()
    days = [end - timedelta(days=offset) for offset in range(6, -1, -1)]
    counts = [snapshot.tokens.get(day, 0) for day in days]
    label(draw, (292, top + 10), compact(sum(counts)), 18, TEAL, "bold", "rt")
    baseline = bottom - 27
    ceiling = max(max(counts), 1)
    draw.line((27, baseline + 2, 292, baseline + 2), fill=BORDER)
    for index, count in enumerate(counts):
        x = 27 + index * 40
        if count:
            height = max(2, round((baseline - top - 35) * count / ceiling))
            color = TEAL if index == 6 else "#4A8B83"
            draw.rounded_rectangle((x, baseline - height, x + 24, baseline - 1),
                                   radius=3, fill=color)
    label(draw, (27, bottom - 16), days[0].strftime("%m/%d"), 11, MUTED, "mono")
    label(draw, (292, bottom - 16), days[-1].strftime("%m/%d"), 11, MUTED, "mono", "rt")


def page(title, subtitle, accent):
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH - 1, 3), fill=accent)
    label(draw, (16, 18), subtitle, 13, accent, "bold")
    label(draw, (15, 38), title, 47, TEXT, "bold")
    return image, draw


def badge(draw, status, color):
    width = max(47, round(draw.textlength(status, font=font(12, "bold"))) + 20)
    draw.rounded_rectangle((304 - width, 15, 304, 39), radius=12, outline=color)
    label(draw, (304 - width / 2, 22), status, 12, color, "bold", "mt")


def render(snapshot, now, demo=False):
    image, draw = page("ChatGPT", "WORK + CODEX", TEAL)

    if demo:
        status, color = "DEMO", SKY
    elif len(snapshot.errors) == 2:
        status = "STALE" if snapshot.limits_at or snapshot.tokens_at else "OFFLINE"
        color = AMBER
    elif snapshot.errors:
        status, color = "PARTIAL", AMBER
    else:
        status, color = "LIVE", TEAL
    badge(draw, status, color)

    windows = snapshot.windows or ()
    for index, window in enumerate(windows):
        quota_card(draw, 96 + index * 110, window, now, (TEAL, SKY)[index])
    if not windows:
        panel(draw, 96, 102)
        message = "Quota unavailable" if snapshot.windows is None else "No quota window reported"
        label(draw, (27, 120), message, 20, TEXT, "bold")
    token_chart(draw, 96 + max(1, len(windows)) * 110, snapshot, now)

    label(draw, (16, 450), "LAST SYNC", 12, MUTED, "bold")
    times = [stamp for stamp in (snapshot.limits_at, snapshot.tokens_at) if stamp]
    last_sync = min(times).strftime("%H:%M:%S") if times else "--:--:--"
    label(draw, (304, 448), last_sync, 17, TEXT, "mono", "rt")
    return image


def render_claude(usage, now, demo=False):
    image, draw = page("Claude", "SUBSCRIPTION USAGE", CLAUDE)
    if usage is None:
        panel(draw, 96, 102)
        label(draw, (27, 119), "Waiting for usage data", 21, TEXT, "bold")
        label(draw, (27, 156), "Claude Code status line", 16, MUTED)
        return image
    expired = any(window.reset_at <= now.timestamp() for window in usage.windows)
    if demo:
        badge(draw, "DEMO", SKY)
    elif expired:
        badge(draw, "UPDATE DUE", AMBER)
    elif now - usage.received_at > timedelta(minutes=15):
        badge(draw, "CACHED", AMBER)
    else:
        badge(draw, "RECENT", CLAUDE)
    for index, window in enumerate(usage.windows):
        top = 96 + index * 110
        if window.reset_at > now.timestamp():
            quota_card(draw, top, window, now, CLAUDE)
        else:
            panel(draw, top, 102)
            label(draw, (27, top + 12), window_name(window.minutes), 13, MUTED, "bold")
            label(draw, (27, top + 42), "Awaiting new limit data", 20, TEXT, "bold")

    label(draw, (16, 332), "UPDATES AFTER CLAUDE CODE REPLIES", 12, MUTED, "bold")
    label(draw, (16, 450), "LAST RECEIVED", 12, MUTED, "bold")
    label(draw, (304, 448), usage.received_at.strftime("%m/%d %H:%M"), 16, TEXT, "mono", "rt")
    return image


def demo_image(path, claude=False):
    now = datetime.fromisoformat("2026-11-16T19:24:30+08:00")
    if claude:
        sample = ClaudeUsage(now, (
            Window(21, 300, int(now.timestamp()) + 6680),
            Window(54, 10080, int(now.timestamp()) + 259200),
        ))
        render_claude(sample, now, demo=True).save(path)
        return
    end = now.astimezone(UTC).date()
    snapshot = Snapshot(
        (Window(25, 300, int(now.timestamp()) + 8650),
         Window(59, 10080, int(now.timestamp()) + 189000)),
        {end - timedelta(days=offset): count for offset, count in
         enumerate((940000, 1600000, 820000, 510000, 2400000, 450000, 730000))},
        now,
        now,
    )
    render(snapshot, now, demo=True).save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, help="override the saved usage polling interval (default 30)")
    parser.add_argument("--codex", help="path to the Codex executable")
    parser.add_argument("--port", help="USB device selector by serial path (default: autodetect)")
    parser.add_argument("--once", action="store_true", help="fetch and write one hardware frame")
    preview = parser.add_mutually_exclusive_group()
    preview.add_argument("--preview", type=Path, help="save a ChatGPT demo PNG")
    preview.add_argument("--preview-claude", type=Path, help="save a Claude demo PNG")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.preview or args.preview_claude:
        demo_image(args.preview or args.preview_claude, claude=bool(args.preview_claude))
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
    started = time.monotonic()
    last_poll = None
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
            mode = "chatgpt" if args.once else preferences.mode
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

            elapsed = time.monotonic() - started
            now = datetime.now().astimezone()
            rotate_to_claude = mode == "rotate" and int(elapsed // preferences.page_seconds) % 2
            claude = read_usage() if mode == "claude" or rotate_to_claude else None
            frame = render_claude(claude, now) if mode == "claude" or claude else render(snapshot, now)
            try:
                screen.show(frame, brightness=preferences.brightness)
            except OSError as error:
                if usb_offline is not True or args.once:
                    logging.warning("USB display unavailable: %s", error)
                screen.close()
                usb_offline = True
            else:
                if usb_offline is not False:
                    logging.info("Dashboard frame sent to USB display")
                usb_offline = False
            if args.once:
                return int(usb_offline or bool(snapshot.errors))
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

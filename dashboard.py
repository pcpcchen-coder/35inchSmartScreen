#!/usr/bin/env python3
"""Live ChatGPT and Claude usage dashboard for a TURZX 3.5-inch screen."""

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


def allowance(window, accent):
    remaining = max(0, min(100, 100 - window.used))
    color = RED if remaining <= 10 else AMBER if remaining <= 25 else accent
    return remaining, color


def quota_card(draw, top, window, now, base_color, *, reset_text=None):
    panel(draw, top, 102)
    remaining, color = allowance(window, base_color)
    label(draw, (27, top + 12), window_name(window.minutes), 13, MUTED, "bold")
    label(draw, (26, top + 28), f"{remaining}%", 43, color, "bold")
    label(draw, (292, top + 37), "LEFT", 13, color, "bold", "rt")
    label(draw, (292, top + 56), reset_text or reset_label(window.reset_at, now), 14, TEXT, anchor="rt")
    draw.rounded_rectangle((27, top + 80, 292, top + 88), radius=4, fill=BORDER)
    if remaining:
        draw.rounded_rectangle((27, top + 80, 27 + round(265 * remaining / 100), top + 88),
                               radius=4, fill=color)


def compact(value):
    for divisor, suffix in ((10**12, "T"), (10**9, "B"), (10**6, "M"), (10**3, "K")):
        if value >= divisor:
            return f"{value / divisor:.1f}{suffix}"
    return str(value)


def token_chart(draw, top, snapshot, now, *, bottom=431, heading="TOKENS / 7 DAYS"):
    panel(draw, top, bottom - top + 1)
    label(draw, (27, top + 12), heading, 13, MUTED, "bold")
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


def chat_status(snapshot):
    if len(snapshot.errors) == 2:
        return ("STALE" if snapshot.limits_at or snapshot.tokens_at else "OFFLINE", AMBER)
    if snapshot.errors:
        return "PARTIAL", AMBER
    return "LIVE", TEAL


def claude_status(usage, now):
    if usage is None:
        return "WAITING", MUTED
    if any(quota_expired(window, now) for window in usage.windows):
        return "UPDATE DUE", AMBER
    if now - usage.received_at > timedelta(minutes=15):
        return "CACHED", AMBER
    return ("SNAPSHOT" if usage.source == "desktop" else "RECENT", CLAUDE)


def quota_expired(window, now):
    return window.reset_at is not None and window.reset_at <= now.timestamp()


def session_not_started(window):
    return window.reset_at is None and window.minutes == 300 and window.used == 0


def render(snapshot, now, demo=False):
    image, draw = page("ChatGPT", "WORK + CODEX", TEAL)
    badge(draw, *(("DEMO", SKY) if demo else chat_status(snapshot)))

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
        label(draw, (27, 156), "Import or connect Claude Code", 15, MUTED)
        return image
    badge(draw, *(("DEMO", SKY) if demo else claude_status(usage, now)))
    for index, window in enumerate(usage.windows):
        top = 96 + index * 110
        if not quota_expired(window, now):
            reset_text = "Starts with first message" if session_not_started(window) else None
            quota_card(draw, top, window, now, CLAUDE, reset_text=reset_text)
        else:
            panel(draw, top, 102)
            label(draw, (27, top + 12), window_name(window.minutes), 13, MUTED, "bold")
            label(draw, (27, top + 42), "Awaiting new limit data", 20, TEXT, "bold")

    source_text = ("IMPORTED FROM CLAUDE DESKTOP" if usage.source == "desktop"
                   else "UPDATES AFTER CLAUDE CODE REPLIES")
    label(draw, (16, 332), source_text, 12, MUTED, "bold")
    label(draw, (16, 450), "LAST IMPORTED" if usage.source == "desktop" else "LAST RECEIVED",
          12, MUTED, "bold")
    label(draw, (304, 448), usage.received_at.strftime("%m/%d %H:%M"), 16, TEXT, "mono", "rt")
    return image


def compact_quota(draw, box, window, now, accent, *, expired=False):
    left, top, right, bottom = box
    draw.rounded_rectangle(box, radius=12, fill=PANEL, outline=BORDER)
    label(draw, (left + 12, top + 10), window_name(window.minutes), 12, MUTED, "bold")
    if expired:
        label(draw, (left + 12, top + 29), "–", 35, MUTED, "bold")
        label(draw, (left + 12, top + 71), "Awaiting update", 12, MUTED)
        return

    remaining, color = allowance(window, accent)
    label(draw, (left + 11, top + 25), f"{remaining}%", 36, color, "bold")
    track_left, track_right = left + 12, right - 12
    draw.rounded_rectangle((track_left, top + 62, track_right, top + 66), radius=2, fill=BORDER)
    if remaining:
        filled = round((track_right - track_left) * remaining / 100)
        draw.rounded_rectangle((track_left, top + 62, track_left + filled, top + 66),
                               radius=2, fill=color)
    reset = "Starts on first use" if session_not_started(window) else reset_label(window.reset_at, now)
    label(draw, (left + 12, top + 74), reset, 12, TEXT)


def provider_section(draw, top, title, accent, status, stamp, windows, now, *, waiting):
    label(draw, (16, top), title, 25, accent, "bold")
    text, color = status
    if stamp is not None:
        time_format = "%H:%M" if stamp.date() == now.date() else "%m/%d %H:%M"
        text += "  ·  " + stamp.strftime(time_format)
    label(draw, (304, top + 8), text, 12, color, "bold", "rt")

    top += 32
    if not windows:
        panel(draw, top, 93)
        label(draw, (27, top + 35), waiting, 18)
        return

    spans = ((14, 305),) if len(windows) == 1 else ((14, 155), (165, 305))
    for window, (left, right) in zip(windows, spans):
        compact_quota(draw, (left, top, right, top + 92), window, now, accent,
                      expired=quota_expired(window, now))


def render_combined(snapshot, claude, now, demo=False):
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 159, 3), fill=TEAL)
    draw.rectangle((160, 0, WIDTH - 1, 3), fill=CLAUDE)
    label(draw, (15, 17), "AI Usage", 31, TEXT, "bold")
    label(draw, (304, 24), "DEMO · REMAINING" if demo else "REMAINING", 12, MUTED, "bold", "rt")
    draw.line((15, 56, 305, 56), fill=BORDER)

    provider_section(draw, 67, "ChatGPT", TEAL, chat_status(snapshot),
                     snapshot.limits_at, snapshot.windows, now, waiting="Waiting for ChatGPT usage")
    provider_section(draw, 207, "Claude", CLAUDE, claude_status(claude, now),
                     claude.received_at if claude else None, claude.windows if claude else None,
                     now, waiting="Import Claude App usage")
    token_chart(draw, 343, snapshot, now, bottom=466, heading="CHATGPT TOKENS / 7 DAYS")
    return image


def demo_image(path, mode):
    now = datetime.fromisoformat("2026-11-16T19:24:30+08:00")
    sample = ClaudeUsage(now, (
        Window(21, 300, int(now.timestamp()) + 6680),
        Window(54, 10080, int(now.timestamp()) + 259200),
    ), "desktop")
    end = now.astimezone(UTC).date()
    snapshot = Snapshot(
        (Window(25, 300, int(now.timestamp()) + 8650),
         Window(59, 10080, int(now.timestamp()) + 189000)),
        {end - timedelta(days=offset): count for offset, count in
         enumerate((940000, 1600000, 820000, 510000, 2400000, 450000, 730000))},
        now,
        now,
    )
    if mode == "claude":
        image = render_claude(sample, now, demo=True)
    elif mode == "combined":
        image = render_combined(snapshot, sample, now, demo=True)
    else:
        image = render(snapshot, now, demo=True)
    image.save(path)


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
            if mode == "combined":
                frame = render_combined(snapshot, claude, now)
            elif mode == "claude":
                frame = render_claude(claude, now)
            else:
                frame = render(snapshot, now)
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

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from claude_usage import ClaudeUsage
from dashboard import Snapshot, status_messages
from monitor_status import Reachability
from preferences import Preferences
from usage import Window


class MonitorStatusTests(unittest.TestCase):
    def test_requires_two_consecutive_failed_checks_and_clears_on_recovery(self):
        monitor = Reachability()
        preferences = Preferences(nous_core_port=8080)
        with patch("monitor_status.time.monotonic", side_effect=(0, 15, 30, 60)), \
             patch("monitor_status.reachable", side_effect=(False, False, True)) as probe:
            monitor.refresh(preferences)
            self.assertEqual(monitor.unreachable, ())
            monitor.refresh(preferences)
            self.assertEqual(probe.call_count, 1)
            monitor.refresh(preferences)
            self.assertEqual(monitor.unreachable, ("Nous Core",))
            monitor.refresh(preferences)
            self.assertEqual(monitor.unreachable, ())

    def test_status_indicates_delay_low_quota_and_service_failure(self):
        now = datetime.fromisoformat("2026-11-17T07:00:00+08:00")
        reset = int((now + timedelta(hours=2)).timestamp())
        chatgpt = Snapshot((Window(93, 300, reset),), now)
        claude = ClaudeUsage(now - timedelta(minutes=4), (Window(38, 10080, reset),), "web")
        self.assertEqual(status_messages(chatgpt, claude, now, "combined", ("Pi",)), [
            "Claude sync delayed", "ChatGPT 7% left", "Pi unreachable",
        ])

    def test_idle_session_is_healthy_but_unknown_reset_is_reported(self):
        now = datetime.fromisoformat("2026-11-17T07:00:00+08:00")
        idle = ClaudeUsage(now, (Window(0, 300, None, True),), "web")
        unknown = ClaudeUsage(now, (Window(0, 300, None, False),), "web")
        self.assertEqual(status_messages(Snapshot(), idle, now, "claude", ()), [])
        self.assertEqual(status_messages(Snapshot(), unknown, now, "claude", ()),
                         ["Claude reset time unavailable"])

import unittest
from datetime import datetime, timedelta

from claude_usage import ClaudeUsage
from dashboard import Snapshot, chat_status, claude_status, health_mark
from usage import Window


class UsageHealthTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-11-17T07:00:00+08:00")
        self.reset = int((self.now + timedelta(hours=2)).timestamp())

    def test_chatgpt_health_reflects_sync_and_not_remaining_amount(self):
        windows = (Window(93, 300, self.reset),)
        healthy = Snapshot(windows, self.now)
        failed = Snapshot(windows, self.now, True)
        for snapshot, symbol in ((healthy, "O"), (failed, "X"), (Snapshot(), "X"),
                                 (Snapshot((), self.now), "X")):
            self.assertEqual(health_mark(chat_status(snapshot, self.now)[0])[0], symbol)

    def test_claude_mark_recovers_with_a_new_sync(self):
        windows = (Window(20, 300, self.reset),)
        stale = ClaudeUsage(self.now - timedelta(minutes=4), windows, "web")
        fresh = ClaudeUsage(self.now, windows, "web")
        old_snapshot = ClaudeUsage(self.now - timedelta(minutes=20), windows, "desktop")
        for usage, symbol in ((None, "X"), (stale, "X"), (fresh, "O"), (old_snapshot, "X")):
            self.assertEqual(health_mark(claude_status(usage, self.now)[0])[0], symbol)

    def test_idle_session_is_healthy_and_missing_reset_is_not(self):
        idle = ClaudeUsage(self.now, (Window(0, 300, None, True),), "web")
        unknown = ClaudeUsage(self.now, (Window(0, 300, None, False),), "web")
        expired = ClaudeUsage(self.now, (Window(25, 300, 1),), "web")
        for usage, symbol in ((idle, "O"), (unknown, "X"), (expired, "X")):
            self.assertEqual(health_mark(claude_status(usage, self.now)[0])[0], symbol)

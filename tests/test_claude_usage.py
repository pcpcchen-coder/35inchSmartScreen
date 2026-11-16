import json
import tempfile
import unittest
from pathlib import Path

from claude_usage import read_usage, write_usage
from usage import Window


class ClaudeUsageTests(unittest.TestCase):
    def test_retains_only_quota_data_and_does_not_erase_it_on_empty_updates(self):
        payload = {
            "session_id": "example-private-session",
            "workspace": {"current_dir": "/example/private"},
            "rate_limits": {
                "five_hour": {"used_percentage": 21.4, "resets_at": 1794830000},
                "seven_day": {"used_percentage": 54, "resets_at": 1794976735},
                "spend_limit": {"used_percentage": 1, "resets_at": 1794976735},
            },
        }
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "cache" / "claude-usage.json"
            self.assertIsNone(read_usage(path))
            write_usage(payload, path)
            cached = json.loads(path.read_text())
            self.assertEqual(set(cached), {"received_at", "rate_limits"})
            self.assertEqual(set(cached["rate_limits"]), {"five_hour", "seven_day"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            snapshot = read_usage(path)
            self.assertEqual(snapshot.windows, (
                Window(21, 300, 1794830000), Window(54, 10080, 1794976735),
            ))
            self.assertEqual(write_usage({}, path), {})
            self.assertEqual(read_usage(path), snapshot)

    def test_accepts_weekly_only_and_skips_malformed_cache(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "claude-usage.json"
            write_usage({"rate_limits": {
                "five_hour": {"used_percentage": "invalid", "resets_at": 1794830000},
                "seven_day": {"used_percentage": 0, "resets_at": 1794976735},
            }}, path)
            self.assertEqual(read_usage(path).windows, (Window(0, 10080, 1794976735),))
            path.write_text("not JSON")
            self.assertIsNone(read_usage(path))

    def test_desktop_snapshot_accepts_an_inactive_session_without_a_reset(self):
        payload = {"rate_limits": {
            "five_hour": {"used_percentage": 0},
            "seven_day": {"used_percentage": 24, "resets_at": 1794976735},
        }}
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "claude-usage.json"
            write_usage(payload, path, source="desktop")
            snapshot = read_usage(path)
            self.assertEqual(snapshot.source, "desktop")
            self.assertEqual(snapshot.windows, (Window(0, 300, None), Window(24, 10080, 1794976735)))
            write_usage(payload, path)
            snapshot = read_usage(path)
            self.assertEqual(snapshot.source, "statusline")
            self.assertEqual(snapshot.windows, (Window(24, 10080, 1794976735),))

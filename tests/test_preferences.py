import tempfile
import unittest
from pathlib import Path

from preferences import Preferences, Subscription, read_preferences, set_preference, set_subscription


class PreferencesTests(unittest.TestCase):
    def test_settings_preserve_prior_choices_and_reject_invalid_values(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "prefs" / "preferences.json"
            self.assertEqual(read_preferences(path), Preferences())
            set_preference("mode", "claude", path)
            set_preference("brightness", "60", path)
            set_preference("blank_on_stop", "true", path)
            with self.assertRaises(ValueError):
                set_preference("poll_seconds", "0", path)
            self.assertEqual(read_preferences(path), Preferences(
                mode="claude", brightness=60, blank_on_stop=True,
            ))

    def test_malformed_or_wrong_type_settings_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "preferences.json"
            path.write_text('{"poll_seconds": true, "page_seconds": 15, "brightness": null}')
            self.assertEqual(read_preferences(path), Preferences())
            path.write_text("corrupt JSON")
            self.assertEqual(read_preferences(path), Preferences())

    def test_old_rotation_settings_use_combined_view_and_keep_other_preferences(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "preferences.json"
            path.write_text('{"mode": "rotate", "page_seconds": 10, "poll_seconds": 15, "brightness": 60}')
            self.assertEqual(read_preferences(path), Preferences(
                mode="combined", poll_seconds=15, brightness=60,
            ))

    def test_subscription_dates_can_be_edited_independently_and_cleared(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "preferences.json"
            set_preference("brightness", "80", path)
            set_subscription("chatgpt", "renews", "2027-02-28", path)
            set_subscription("claude", "ends", "2027-02-15", path)
            with self.assertRaises(ValueError):
                set_subscription("claude", "ends", "2027-02-30", path)
            self.assertEqual(read_preferences(path), Preferences(
                brightness=80, chatgpt_subscription=Subscription("renews", "2027-02-28"),
                claude_subscription=Subscription("ends", "2027-02-15"),
            ))
            set_subscription("claude", "clear", path=path)
            self.assertIsNone(read_preferences(path).claude_subscription)

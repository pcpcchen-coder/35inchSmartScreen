import tempfile
import unittest
from pathlib import Path

from preferences import Preferences, read_preferences, set_preference


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

import unittest
from unittest.mock import Mock, patch

from PIL import Image

from turzx import BULK_OUT, CHUNK_BYTES, HEIGHT, WIDTH, Display, command


class DisplayTests(unittest.TestCase):
    def test_transfers_keep_headers_separate_from_rgb565_pixels(self):
        device = Mock()
        device.write.side_effect = lambda endpoint, data, timeout: len(data)
        frame = Image.new("RGB", (WIDTH, HEIGHT), (255, 0, 0))
        display = Display(None)

        with patch("turzx.find_device", return_value=device), patch("turzx.usb.util.claim_interface"):
            display.show(frame)

        transfers = []
        for call in device.write.call_args_list:
            endpoint, data = call.args
            self.assertEqual(endpoint, BULK_OUT)
            transfers.append(bytes(data))

        frame_size = WIDTH * HEIGHT * 2
        frame_chunks = (frame_size + CHUNK_BYTES - 1) // CHUNK_BYTES
        full_frame_header = command(197, 0, 0, WIDTH - 1, HEIGHT - 1)
        self.assertEqual(transfers[0], full_frame_header)
        self.assertEqual(b"".join(transfers[1:frame_chunks + 1]), bytes(frame_size))
        self.assertEqual(transfers[frame_chunks + 1], b"\0\0\0\0\0\x6d")
        self.assertEqual(transfers[frame_chunks + 2], b"\0\0\0\0\0\x79\x64\x01\x40\x01\xe0")
        self.assertEqual(transfers[frame_chunks + 3], full_frame_header)
        pixels = transfers[frame_chunks + 4:]
        self.assertEqual(b"".join(pixels), b"\x00\xf8" * (WIDTH * HEIGHT))
        self.assertTrue(all(len(chunk) % 64 == 0 for chunk in pixels))

        device.write.reset_mock()
        display.show(frame)
        device.write.assert_not_called()

        patched = frame.copy()
        patched.putpixel((9, 11), (0, 255, 0))
        display.show(patched)
        self.assertEqual([bytes(call.args[1]) for call in device.write.call_args_list],
                         [command(197, 9, 11, 9, 11), b"\xe0\x07"])

    def test_brightness_changes_even_when_the_frame_is_unchanged(self):
        display = Display(None)
        display.device = Mock()
        display.device.write.side_effect = lambda endpoint, data, timeout: len(data)
        frame = Image.new("RGB", (WIDTH, HEIGHT))
        display.previous = frame

        display.show(frame, brightness=60)
        display.show(frame, brightness=60)
        display.power_off()
        self.assertEqual([bytes(call.args[1]) for call in display.device.write.call_args_list],
                         [command(110, x=102), command(108)])

    def test_short_write_does_not_advance_the_cached_image(self):
        display = Display(None)
        display.device = Mock()
        display.device.write.return_value = 1
        with self.assertRaisesRegex(OSError, "Incomplete USB transfer"):
            display.show(Image.new("RGB", (WIDTH, HEIGHT)))
        self.assertIsNone(display.previous)


if __name__ == "__main__":
    unittest.main()

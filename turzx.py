"""RGB565 output for the TURZX 3.5-inch USB serial display."""

import struct
from pathlib import Path

from PIL import ImageChops
from serial import Serial
from serial.tools.list_ports import comports

WIDTH, HEIGHT = 320, 480
USB_ID = (0x1A86, 0x5722)


def find_port():
    matches = [
        port.device for port in comports()
        if (port.vid, port.pid) == USB_ID and port.serial_number in
        {"USB35INCHIPS", "USB35INCHIPSV2"}
    ]
    if len(matches) != 1:
        raise OSError("Connect one TURZX 3.5-inch display or specify --port")
    return matches[0]


def command(opcode, x=0, y=0, right=0, bottom=0):
    packed = (x << 38) | (y << 28) | (right << 18) | (bottom << 8) | opcode
    return packed.to_bytes(6, "big")


class Display:
    def __init__(self, port):
        self.port = port
        self.serial = None
        self.previous = None

    def close(self):
        if self.serial is not None:
            self.serial.close()
            self.serial = None
        self.previous = None

    def send(self, data):
        self.serial.write(data)
        # Let macOS finish each transfer before queuing the next chunk.
        self.serial.flush()

    def show(self, image):
        if self.serial is not None and not Path(self.serial.port).exists():
            self.close()
        if self.serial is None:
            self.serial = Serial(
                self.port or find_port(), 115200, rtscts=True, write_timeout=3, exclusive=True,
            )
            self.send(command(109))
            # Set portrait orientation and native dimensions.
            orientation = struct.pack(">BHH", 100, WIDTH, HEIGHT) + bytes(5)
            self.send(command(121) + orientation)

        bounds = (0, 0, WIDTH, HEIGHT)
        if self.previous is not None:
            bounds = ImageChops.difference(self.previous, image).getbbox()
            if bounds is None:
                return
        left, top, right, bottom = bounds
        rgb = iter(image.crop(bounds).tobytes())
        pixels = bytearray((right - left) * (bottom - top) * 2)
        for index, (red, green, blue) in enumerate(zip(rgb, rgb, rgb)):
            pixels[index * 2] = (green & 0x1C) << 3 | blue >> 3
            pixels[index * 2 + 1] = (red & 0xF8) | green >> 5

        self.send(command(197, left, top, right - 1, bottom - 1))
        chunk_size = WIDTH * 8
        for offset in range(0, len(pixels), chunk_size):
            self.send(pixels[offset:offset + chunk_size])
        self.previous = image

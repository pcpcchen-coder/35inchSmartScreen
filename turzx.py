"""Send RGB565 images to the TURZX 3.5-inch USB bulk endpoint."""

import errno
import struct

import usb.core
import usb.util
from PIL import ImageChops
from serial.tools.list_ports import comports

WIDTH, HEIGHT = 320, 480
USB_ID = (0x1A86, 0x5722)
SERIAL_NUMBERS = {"USB35INCHIPS", "USB35INCHIPSV2"}
DATA_INTERFACE = 1
BULK_OUT = 0x03
CHUNK_BYTES = 4096  # Multiple of the endpoint's 64-byte USB packet size.


def find_device(port):
    route = None
    if port:
        for candidate in comports():
            if candidate.device == port and candidate.location:
                bus, ports = candidate.location.split("-", 1)
                route = (int(bus), tuple(map(int, ports.split("."))))
                break
        if route is None:
            raise OSError(f"Cannot resolve the USB location of {port}")

    try:
        devices = usb.core.find(find_all=True, idVendor=USB_ID[0], idProduct=USB_ID[1])
        matches = [
            device for device in devices
            if (route is None or (device.bus, device.port_numbers) == route)
            and device.serial_number in SERIAL_NUMBERS
        ]
    except usb.core.NoBackendError as error:
        raise OSError("libusb is required. Install it with brew install libusb.") from error
    if len(matches) != 1:
        raise OSError("Connect one TURZX 3.5-inch display or specify --port")
    return matches[0]


def command(opcode, x=0, y=0, right=0, bottom=0):
    packed = (x << 38) | (y << 28) | (right << 18) | (bottom << 8) | opcode
    return packed.to_bytes(6, "big")


class Display:
    def __init__(self, port):
        self.port = port
        self.device = None
        self.previous = None
        self.brightness = None

    def close(self):
        if self.device is not None:
            try:
                usb.util.dispose_resources(self.device)
            except usb.core.USBError:
                pass  # The panel may already have been unplugged.
            finally:
                self.device = None
        self.previous = None
        self.brightness = None

    def connect(self):
        self.device = find_device(self.port)
        try:
            usb.util.claim_interface(self.device, DATA_INTERFACE)
        except usb.core.USBError as error:
            if error.errno != errno.EACCES or not self.device.is_kernel_driver_active(DATA_INTERFACE):
                raise
            # On macOS the CDC driver may initially own this interface.
            self.device.set_configuration()
            usb.util.claim_interface(self.device, DATA_INTERFACE)

        # Finish any interrupted bitmap before sending setup commands. When the
        # panel is idle, the same header and zero pixels draw a black frame.
        self.bitmap((0, 0, WIDTH, HEIGHT), bytes(WIDTH * HEIGHT * 2))
        self.send(command(109))
        self.send(command(121) + struct.pack(">BHH", 100, WIDTH, HEIGHT))

    def send(self, data):
        # Commands must each start at a USB transfer boundary.
        if self.device.write(BULK_OUT, data, timeout=3000) != len(data):
            raise OSError("Incomplete USB transfer")

    def bitmap(self, bounds, pixels):
        left, top, right, bottom = bounds
        self.send(command(197, left, top, right - 1, bottom - 1))
        for offset in range(0, len(pixels), CHUNK_BYTES):
            self.send(pixels[offset:offset + CHUNK_BYTES])

    def power_off(self):
        if self.device is not None:
            self.send(command(108))

    def show(self, image, brightness=None):
        if self.device is None:
            self.connect()
        if brightness is not None and brightness != self.brightness:
            self.send(command(110, x=(100 - brightness) * 255 // 100))
            self.brightness = brightness

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

        self.bitmap(bounds, pixels)
        self.previous = image

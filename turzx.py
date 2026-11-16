"""Send RGB565 images to the TURZX 3.5-inch USB bulk endpoint."""

import errno
import struct

import usb.core
import usb.util
from PIL import Image, ImageChops
from serial.tools.list_ports import comports

WIDTH, HEIGHT = 320, 480
USB_ID = (0x1A86, 0x5722)
SERIAL_NUMBERS = {"USB35INCHIPS", "USB35INCHIPSV2"}
DATA_INTERFACE = 1
BULK_OUT = 0x03
CHUNK_BYTES = 4096  # Multiple of the endpoint's 64-byte USB packet size.
BAND_ROWS = 16
# Bias toward fewer bitmap headers when the pixel cost is close.
BITMAP_OVERHEAD_PIXELS = 256


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


def bitmap_cost(bounds):
    left, top, right, bottom = bounds
    return (right - left) * (bottom - top) + BITMAP_OVERHEAD_PIXELS


def changed_bands(difference):
    bounds = difference.getbbox()
    if bounds is None:
        return []

    left, top, right, bottom = bounds
    regions = []
    for y in range(top, bottom, BAND_ROWS):
        band = difference.crop((left, y, right, min(y + BAND_ROWS, bottom))).getbbox()
        if band is None:
            continue
        region = (left + band[0], y + band[1], left + band[2], y + band[3])
        if regions:
            previous = regions[-1]
            merged = (min(previous[0], region[0]), previous[1],
                      max(previous[2], region[2]), region[3])
            if bitmap_cost(merged) <= bitmap_cost(previous) + bitmap_cost(region):
                regions[-1] = merged
                continue
        regions.append(region)
    return regions


def changed_regions(previous, image):
    difference = ImageChops.difference(previous, image)
    bounds = difference.getbbox()
    if bounds is None:
        return []
    rows = changed_bands(difference)
    columns = [
        (top, left, bottom, right)
        for left, top, right, bottom in changed_bands(difference.transpose(Image.Transpose.TRANSPOSE))
    ]
    return min(([bounds], rows, columns), key=lambda plan: sum(map(bitmap_cost, plan)))


def rgb565(image):
    rgb = iter(image.tobytes())
    pixels = bytearray(image.width * image.height * 2)
    for index, (red, green, blue) in enumerate(zip(rgb, rgb, rgb)):
        pixels[index * 2] = (green & 0x1C) << 3 | blue >> 3
        pixels[index * 2 + 1] = (red & 0xF8) | green >> 5
    return pixels


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

        regions = [(0, 0, WIDTH, HEIGHT)] if self.previous is None else changed_regions(self.previous, image)
        for bounds in regions:
            self.bitmap(bounds, rgb565(image.crop(bounds)))
        self.previous = image

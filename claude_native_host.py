"""Receive a quota-only snapshot via Chrome's local Native Messaging protocol."""

import json
import struct
import sys

from claude_usage import write_usage

LENGTH = struct.Struct("=I")
MAX_BYTES = 4096


def handle(incoming, outgoing):
    success = False
    try:
        (size,) = LENGTH.unpack(incoming.read(LENGTH.size))
        if 0 < size <= MAX_BYTES:
            message = incoming.read(size)
            if len(message) == size:
                success = bool(write_usage(json.loads(message), source="web"))
    except (OSError, ValueError, struct.error):
        pass
    response = json.dumps({"ok": success}).encode()
    outgoing.write(LENGTH.pack(len(response)) + response)
    outgoing.flush()


if __name__ == "__main__":
    handle(sys.stdin.buffer, sys.stdout.buffer)

"""Track reachability of the optional local Nous and Pi services."""

import socket
import time

CHECK_SECONDS = 30
TIMEOUT_SECONDS = 0.6


def reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


class Reachability:
    def __init__(self):
        self.targets = {}
        self.failures = {}
        self.next_check = 0

    def refresh(self, preferences):
        targets = {}
        if preferences.nous_core_port is not None:
            targets["Nous Core"] = ("127.0.0.1", preferences.nous_core_port)
        if preferences.pi_host is not None:
            targets["Pi"] = (preferences.pi_host, 22)
        now = time.monotonic()
        if targets == self.targets and now < self.next_check:
            return

        self.failures = {
            name: 0 if reachable(*address) else
            1 + (self.failures.get(name, 0) if self.targets.get(name) == address else 0)
            for name, address in targets.items()
        }
        self.targets = targets
        self.next_check = now + CHECK_SECONDS

    @property
    def unreachable(self):
        return tuple(name for name, count in self.failures.items() if count >= 2)

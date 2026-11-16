"""Read ChatGPT usage through the local Codex App Server."""

import json
import select
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

BUNDLED_CODEX = Path(
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
)


class UsageError(Exception):
    """The server returned an error or an unusable response."""


@dataclass(frozen=True)
class Window:
    used: int
    minutes: int | None
    reset_at: int | None


class CodexServer:
    def __init__(self, executable):
        self.executable = executable
        self.process = None
        self.buffer = bytearray()
        self.request_id = 0

    def close(self):
        if self.process is None:
            return
        process, self.process = self.process, None
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        process.stdin.close()
        process.stdout.close()

    def call(self, method):
        try:
            if self.process is None:
                self.buffer.clear()
                self.process = subprocess.Popen(
                    [self.executable, "app-server", "--listen", "stdio://"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                try:
                    self.request("initialize", {"clientInfo": {
                        "name": "turzx_usage_display", "version": "1.0.0",
                    }})
                    self.send({"method": "initialized"})
                except UsageError:
                    self.close()
                    raise
            return self.request(method)
        except (OSError, ValueError) as error:
            self.close()
            raise UsageError("Codex App Server unavailable") from error

    def send(self, message):
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        self.process.stdin.flush()

    def request(self, method, params=None):
        self.request_id += 1
        request = {"id": self.request_id, "method": method}
        if params is not None:
            request["params"] = params
        self.send(request)

        deadline = time.monotonic() + 8
        while (remaining := deadline - time.monotonic()) > 0:
            end = self.buffer.find(b"\n")
            if end >= 0:
                line = self.buffer[:end]
                del self.buffer[:end + 1]
                message = json.loads(line)
                if message.get("id") == self.request_id and "method" not in message:
                    result = message.get("result")
                    if isinstance(result, dict):
                        return result
                    raise UsageError(f"{method} returned no data")
                continue
            stdout = self.process.stdout
            if not select.select([stdout], [], [], remaining)[0]:
                break
            chunk = stdout.read1(65536)
            if not chunk:
                raise BrokenPipeError("Codex App Server exited")
            self.buffer.extend(chunk)
        raise TimeoutError(f"{method} timed out")


def find_codex():
    return shutil.which("codex") or (str(BUNDLED_CODEX) if BUNDLED_CODEX.is_file() else None)


def quota_windows(response):
    by_id = response.get("rateLimitsByLimitId") or {}
    bucket = by_id.get("codex")
    if bucket is None:
        previous = response.get("rateLimits") or {}
        if previous.get("limitId") not in (None, "codex"):
            return ()
        bucket = previous
    windows = []
    for key in ("primary", "secondary"):
        window = bucket.get(key) or {}
        used = window.get("usedPercent")
        if type(used) is int:
            windows.append(Window(used, window.get("windowDurationMins"), window.get("resetsAt")))
    return tuple(windows)

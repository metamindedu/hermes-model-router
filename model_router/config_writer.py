"""Bounded per-profile worker for the native config CLI dispatcher.

The parent owns validation/CAS/readback. Workers never receive credentials,
renderer commands or paths, and only run the same config-set handler as CLI.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

ALLOWED_KEYS = frozenset({
    "model.provider", "model.default", "model.base_url", "model.api_mode", "agent.reasoning_effort",
    "delegation.provider", "delegation.model", "delegation.reasoning_effort", "delegation.base_url", "delegation.api_mode", "delegation.fallback_providers",
    "auxiliary.compression.provider", "auxiliary.compression.model", "auxiliary.compression.reasoning_effort",
    "auxiliary.title_generation.provider", "auxiliary.title_generation.model", "auxiliary.title_generation.reasoning_effort",
    "fallback_providers", "fallback_model", "skills.disabled", "skills.external_dirs",
})

class ConfigWriterError(RuntimeError):
    pass

class ConfigWriter:
    def __init__(self, env: dict[str, str]):
        self.process = subprocess.Popen(
            [sys.executable, "-u", str(Path(__file__).resolve())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="strict", shell=False, env=env,
            close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.reader: threading.Thread | None = None

    def set(self, key: str, value, timeout: float = 15):
        if key not in ALLOWED_KEYS:
            raise ConfigWriterError("unsupported config key")
        payload = json.dumps({"key": key, "value": value}, ensure_ascii=False, separators=(",", ":"))
        if len(payload.encode("utf-8")) > 65536:
            raise ConfigWriterError("config write payload too large")
        result = queue.Queue(maxsize=1)
        def exchange():
            try:
                # Include startup and pipe backpressure in the same deadline;
                # the controlling thread must never block on write/flush.
                self.process.stdin.write(payload + "\n")
                self.process.stdin.flush()
                result.put(self.process.stdout.readline())
            except Exception:
                result.put(None)
        try:
            self.reader = threading.Thread(target=exchange, daemon=True)
            self.reader.start()
            line = result.get(timeout=timeout)
            reply = json.loads(line) if line else None
            if not isinstance(reply, dict) or reply != {"ok": True}:
                raise ConfigWriterError("config write failed")
        except (OSError, ValueError, queue.Empty) as exc:
            self.close()
            raise ConfigWriterError("config write outcome unavailable") from exc
        finally:
            if self.reader is not None and not self.reader.is_alive():
                self.reader.join()
                self.reader = None

    def close(self):
        """Bounded best-effort teardown with explicit proof, never new writes."""
        try:
            if self.process.poll() is None:
                self.process.terminate()
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            self.process.wait(timeout=2)
        except (OSError, subprocess.SubprocessError):
            try:
                self.process.kill()
            except (OSError, subprocess.SubprocessError):
                pass
            try:
                self.process.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                pass
        if self.reader is not None:
            self.reader.join(timeout=2)
            if self.reader.is_alive():
                # Closing a stream whose lock the blocked exchange owns can
                # itself block. Report unverified cleanup instead.
                return False
        try:
            exited = self.process.poll() is not None
        except (OSError, subprocess.SubprocessError):
            exited = False
        streams_closed = True
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                try:
                    stream.close()
                except (OSError, ValueError):
                    streams_closed = False
        return exited and streams_closed


def main():
    from argparse import Namespace
    from contextlib import redirect_stdout, redirect_stderr
    import io
    from hermes_cli.config import config_command
    for line in sys.stdin:
        try:
            if len(line.encode("utf-8")) > 65537:
                raise ValueError("oversize")
            request = json.loads(line)
            if not isinstance(request, dict) or set(request) != {"key", "value"} or request["key"] not in ALLOWED_KEYS:
                raise ValueError("invalid")
            value = request["value"]
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            # Only this isolated worker's streams are redirected. Native CLI
            # warnings can contain old endpoint details; never forward them.
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                config_command(Namespace(config_command="set", key=request["key"], value=rendered, force=True))
            reply = {"ok": True}
        except (Exception, SystemExit):
            reply = {"ok": False}
        print(json.dumps(reply), flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

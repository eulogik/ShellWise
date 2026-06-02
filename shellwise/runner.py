"""
shellwise.runner

Manages the bundled llama-server binary as a subprocess.
- Allocates a free local port
- Spawns llama-server with the model path
- Polls /health until the server is ready
- Sends chat-completion requests via HTTP (OpenAI-compatible API)
- Cleans up on exit, SIGINT, SIGTERM, and atexit
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# ── binary location ──────────────────────────────────────────────────────────

def _platform_dir() -> Path:
    """Return the bundled binary directory for the current platform."""
    pkg_root = Path(__file__).resolve().parent
    plat = sys.platform
    machine = os.uname().machine if hasattr(os, "uname") else ""

    if plat == "darwin":
        if machine == "arm64":
            return pkg_root / "bin" / "darwin-arm64"
        return pkg_root / "bin" / "darwin-x64"
    if plat.startswith("linux"):
        return pkg_root / "bin" / "linux-x64"
    if plat.startswith("win"):
        return pkg_root / "bin" / "win32"
    raise RuntimeError(f"Unsupported platform: {plat} ({machine})")


def _binary_path() -> Path:
    plat = sys.platform
    name = "llama-server.exe" if plat.startswith("win") else "llama-server"
    d = _platform_dir()
    p = d / name
    if not p.exists():
        raise FileNotFoundError(
            f"shellwise: bundled llama-server not found for {plat} at {p}.\n"
            f"  This usually means the wheel was built without running tools/fetch_binaries.py.\n"
            f"  Falling back to other backends."
        )
    return p


def bundled_binary_available() -> bool:
    try:
        _binary_path()
        return True
    except (FileNotFoundError, RuntimeError):
        return False


# ── port allocation ──────────────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── the runner ───────────────────────────────────────────────────────────────

class LlamaServer:
    """A long-lived llama-server subprocess bound to a model file."""

    def __init__(
        self,
        model_path: Path,
        *,
        n_ctx: int = 2048,
        n_threads: Optional[int] = None,
        host: str = "127.0.0.1",
        startup_timeout: float = 60.0,
        extra_args: Optional[list] = None,
    ):
        self.model_path = Path(model_path)
        self.n_ctx = n_ctx
        self.n_threads = n_threads if n_threads is not None else max(1, (os.cpu_count() or 2) - 1)
        self.host = host
        self.startup_timeout = startup_timeout
        self.extra_args = extra_args or []
        self.port = _free_port()
        self.proc: Optional[subprocess.Popen] = None
        self._registered_cleanup = False

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return  # already running
        binary = _binary_path()
        args = [
            str(binary),
            "--model", str(self.model_path),
            "--host", self.host,
            "--port", str(self.port),
            "--ctx-size", str(self.n_ctx),
            "-t", str(self.n_threads),
            *self.extra_args,
        ]
        # On POSIX, set the process group so we can kill children too.
        kwargs: dict = {}
        if os.name == "posix":
            kwargs["preexec_fn"] = os.setsid
        else:
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        # Silence the server's noisy banner on stderr unless verbose.
        self.proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
        self._wait_ready()
        if not self._registered_cleanup:
            atexit.register(self.stop)
            self._registered_cleanup = True

    def stop(self) -> None:
        if self.proc is None:
            return
        proc = self.proc
        self.proc = None
        if proc.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
        except (ProcessLookupError, OSError):
            pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    # ── health ───────────────────────────────────────────────────────────────

    def _wait_ready(self) -> None:
        url = f"http://{self.host}:{self.port}/health"
        deadline = time.time() + self.startup_timeout
        last_err: Optional[Exception] = None
        while time.time() < deadline:
            # If the process died, surface that immediately.
            if self.proc and self.proc.poll() is not None:
                raise RuntimeError(
                    f"llama-server exited with code {self.proc.returncode} during startup"
                )
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200:
                        return
            except (urllib.error.URLError, ConnectionResetError, OSError) as e:
                last_err = e
                time.sleep(0.2)
        self.stop()
        raise TimeoutError(
            f"llama-server did not become ready in {self.startup_timeout}s "
            f"(last error: {last_err})"
        )

    # ── inference ────────────────────────────────────────────────────────────

    def chat(
        self,
        messages: list,
        *,
        max_tokens: int = 512,
        temperature: float = 0.1,
        timeout: float = 120.0,
    ) -> str:
        """Send a chat-completion request. Returns the assistant's reply text."""
        url = f"http://{self.host}:{self.port}/v1/chat/completions"
        payload = json.dumps({
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()


# ── module-level singleton ───────────────────────────────────────────────────

_server: Optional[LlamaServer] = None


def get_server(model_path: Path) -> LlamaServer:
    """Return a process-wide LlamaServer, starting it lazily on first call."""
    global _server
    if _server is None or _server.proc is None or _server.proc.poll() is not None:
        _server = LlamaServer(model_path)
        _server.start()
    return _server


def shutdown() -> None:
    """Stop the singleton server (if any). Called on process exit."""
    global _server
    if _server is not None:
        _server.stop()
        _server = None

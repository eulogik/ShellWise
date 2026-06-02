import json
import socket
import subprocess
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, call, mock_open, patch

import pytest

from shellwise import runner


# ── platform / binary discovery ──────────────────────────────────────────────

class TestPlatformDir:
    def test_darwin_arm64(self, mocker):
        mocker.patch.object(runner.sys, "platform", "darwin")
        mocker.patch.object(runner.os, "uname", return_value=MagicMock(machine="arm64"))
        d = runner._platform_dir()
        assert d.name == "darwin-arm64"

    def test_darwin_x64(self, mocker):
        mocker.patch.object(runner.sys, "platform", "darwin")
        mocker.patch.object(runner.os, "uname", return_value=MagicMock(machine="x86_64"))
        d = runner._platform_dir()
        assert d.name == "darwin-x64"

    def test_linux_x64(self, mocker):
        mocker.patch.object(runner.sys, "platform", "linux")
        d = runner._platform_dir()
        assert d.name == "linux-x64"

    def test_win32(self, mocker):
        mocker.patch.object(runner.sys, "platform", "win32")
        d = runner._platform_dir()
        assert d.name == "win32"

    def test_unsupported_raises(self, mocker):
        mocker.patch.object(runner.sys, "platform", "beos")
        with pytest.raises(RuntimeError, match="Unsupported platform"):
            runner._platform_dir()


class TestBinaryPath:
    def test_posix_uses_llama_server(self, mocker):
        mocker.patch.object(runner.sys, "platform", "darwin")
        mocker.patch.object(runner.os, "uname", return_value=MagicMock(machine="arm64"))
        mocker.patch.object(Path, "exists", return_value=True)
        p = runner._binary_path()
        assert p.name == "llama-server"

    def test_windows_uses_llama_server_exe(self, mocker):
        mocker.patch.object(runner.sys, "platform", "win32")
        mocker.patch.object(Path, "exists", return_value=True)
        p = runner._binary_path()
        assert p.name == "llama-server.exe"

    def test_missing_raises_with_helpful_message(self, mocker):
        mocker.patch.object(runner.sys, "platform", "darwin")
        mocker.patch.object(runner.os, "uname", return_value=MagicMock(machine="arm64"))
        mocker.patch.object(Path, "exists", return_value=False)
        with pytest.raises(FileNotFoundError, match="bundled llama-server not found"):
            runner._binary_path()


class TestBundledBinaryAvailable:
    def test_true_when_binary_exists(self, mocker):
        mocker.patch.object(runner, "_binary_path", return_value=Path("/tmp/llama-server"))
        assert runner.bundled_binary_available() is True

    def test_false_when_missing(self, mocker):
        mocker.patch.object(
            runner, "_binary_path",
            side_effect=FileNotFoundError("missing"),
        )
        assert runner.bundled_binary_available() is False

    def test_false_when_unsupported_platform(self, mocker):
        mocker.patch.object(runner, "_binary_path", side_effect=RuntimeError("nope"))
        assert runner.bundled_binary_available() is False


# ── port allocation ─────────────────────────────────────────────────────────

class TestFreePort:
    def test_returns_int_in_ephemeral_range(self):
        port = runner._free_port()
        assert isinstance(port, int)
        assert 1024 < port < 65536

    def test_returns_different_ports_on_successive_calls(self):
        # unlikely to collide; if it ever does, retry
        ports = {runner._free_port() for _ in range(5)}
        assert len(ports) >= 4


# ── LlamaServer lifecycle ───────────────────────────────────────────────────

class TestLlamaServerStart:
    def _make_server(self, mocker, **overrides):
        mocker.patch.object(runner, "_binary_path", return_value=Path("/tmp/llama-server"))
        return runner.LlamaServer(
            Path("/tmp/model.gguf"),
            startup_timeout=overrides.pop("startup_timeout", 5.0),
            **overrides,
        )

    def test_start_spawns_subprocess_with_expected_args(self, mocker):
        s = self._make_server(mocker)
        mock_popen = mocker.patch.object(runner.subprocess, "Popen")
        mock_popen.return_value.poll.return_value = None  # alive
        mocker.patch.object(LlamaServer_proxy := type(s), "_wait_ready", lambda self: None)
        s.start()
        args = mock_popen.call_args[0][0]
        assert "llama-server" in args[0]
        assert "--model" in args
        assert "/tmp/model.gguf" in args
        assert "--port" in args
        assert str(s.port) in args
        assert "--host" in args
        assert "127.0.0.1" in args
        # stdout/stderr suppressed
        kwargs = mock_popen.call_args[1]
        assert kwargs["stdout"] == runner.subprocess.DEVNULL
        assert kwargs["stderr"] == runner.subprocess.DEVNULL

    def test_start_is_idempotent(self, mocker):
        s = self._make_server(mocker)
        mock_popen = mocker.patch.object(runner.subprocess, "Popen")
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc
        mocker.patch.object(type(s), "_wait_ready", lambda self: None)
        s.start()
        s.start()
        assert mock_popen.call_count == 1

    def test_start_uses_setsid_on_posix(self, mocker):
        s = self._make_server(mocker)
        mocker.patch.object(runner.os, "name", "posix")
        mock_popen = mocker.patch.object(runner.subprocess, "Popen")
        mock_popen.return_value.poll.return_value = None
        mocker.patch.object(type(s), "_wait_ready", lambda self: None)
        s.start()
        assert mock_popen.call_args[1]["preexec_fn"] == runner.os.setsid


class TestLlamaServerStop:
    def _running(self, mocker):
        s = runner.LlamaServer(Path("/tmp/model.gguf"))
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 1234
        s.proc = proc
        return s, proc

    def test_stop_terminates_process(self, mocker):
        s, proc = self._running(mocker)
        mocker.patch.object(runner.os, "name", "posix")
        mock_killpg = mocker.patch.object(runner.os, "killpg")
        s.stop()
        mock_killpg.assert_called_once()
        proc.wait.assert_called_once()

    def test_stop_force_kills_on_timeout(self, mocker):
        s, proc = self._running(mocker)
        mocker.patch.object(runner.os, "name", "posix")
        mock_killpg = mocker.patch.object(runner.os, "killpg")
        proc.wait.side_effect = [subprocess.TimeoutExpired("x", 5), None]
        s.stop()
        assert mock_killpg.call_count == 2  # SIGTERM, then SIGKILL

    def test_stop_swallows_process_lookup_error(self, mocker):
        s, proc = self._running(mocker)
        mocker.patch.object(runner.os, "name", "posix")
        mocker.patch.object(
            runner.os, "killpg",
            side_effect=ProcessLookupError("already dead"),
        )
        s.stop()  # should not raise

    def test_stop_noop_if_proc_dead(self, mocker):
        s, proc = self._running(mocker)
        proc.poll.return_value = 0
        mock_terminate = mocker.patch.object(proc, "terminate")
        s.stop()
        mock_terminate.assert_not_called()


# ── _wait_ready ─────────────────────────────────────────────────────────────

class TestWaitReady:
    def test_polls_until_200(self, mocker):
        s = runner.LlamaServer(Path("/tmp/model.gguf"), startup_timeout=5.0)
        s.proc = MagicMock()
        s.proc.poll.return_value = None
        # First call: connection refused, second: 200
        responses = [ConnectionResetError("nope"), MagicMock(status=200)]
        responses[1].__enter__ = MagicMock(return_value=responses[1])
        responses[1].__exit__ = MagicMock(return_value=False)
        mock_urlopen = mocker.patch.object(
            runner.urllib.request, "urlopen", side_effect=responses,
        )
        mocker.patch.object(runner.time, "sleep")
        s._wait_ready()
        assert mock_urlopen.call_count == 2

    def test_raises_if_process_exits_during_startup(self, mocker):
        s = runner.LlamaServer(Path("/tmp/model.gguf"), startup_timeout=5.0)
        s.proc = MagicMock()
        s.proc.poll.return_value = 1  # dead
        s.proc.returncode = 1
        with pytest.raises(RuntimeError, match="exited with code 1"):
            s._wait_ready()

    def test_raises_timeout_if_never_ready(self, mocker):
        s = runner.LlamaServer(
            Path("/tmp/model.gguf"),
            startup_timeout=0.0,  # expire immediately
        )
        s.proc = MagicMock()
        s.proc.poll.return_value = None
        mocker.patch.object(
            runner.urllib.request, "urlopen",
            side_effect=urllib.error.URLError("nope"),
        )
        mocker.patch.object(runner.time, "time", side_effect=[0.0, 100.0, 100.0])
        mocker.patch.object(runner.time, "sleep")
        s.proc.terminate = MagicMock()
        s.proc.kill = MagicMock()
        with pytest.raises(TimeoutError, match="did not become ready"):
            s._wait_ready()


# ── chat ────────────────────────────────────────────────────────────────────

class TestChat:
    def test_posts_to_v1_chat_completions(self, mocker):
        s = runner.LlamaServer(Path("/tmp/model.gguf"))
        s.port = 12345
        s.host = "127.0.0.1"
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "  hello  "}}],
        }).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen = mocker.patch.object(
            runner.urllib.request, "urlopen", return_value=mock_resp,
        )
        out = s.chat([{"role": "user", "content": "hi"}])
        assert out == "hello"
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://127.0.0.1:12345/v1/chat/completions"
        body = json.loads(req.data)
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        assert body["max_tokens"] == 512
        assert body["temperature"] == 0.1
        assert body["stream"] is False

    def test_respects_overrides(self, mocker):
        s = runner.LlamaServer(Path("/tmp/model.gguf"))
        s.port = 9
        s.host = "127.0.0.1"
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "x"}}]}
        ).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen = mocker.patch.object(
            runner.urllib.request, "urlopen", return_value=mock_resp,
        )
        s.chat([{"role": "user", "content": "q"}], max_tokens=64, temperature=0.7, timeout=10.0)
        body = json.loads(mock_urlopen.call_args[0][0].data)
        assert body["max_tokens"] == 64
        assert body["temperature"] == 0.7


# ── module-level singleton ──────────────────────────────────────────────────

class TestGetServer:
    def setup_method(self):
        # ensure no leaked singleton between tests
        runner._server = None

    def test_creates_and_starts_new_server(self, mocker):
        mock_srv = MagicMock()
        mock_srv.proc = None
        mocker.patch.object(runner, "LlamaServer", return_value=mock_srv)
        out = runner.get_server(Path("/tmp/model.gguf"))
        mock_srv.start.assert_called_once()
        assert out is mock_srv

    def test_reuses_existing_alive_server(self, mocker):
        existing = MagicMock()
        existing.proc = MagicMock()
        existing.proc.poll.return_value = None  # alive
        runner._server = existing
        mock_ctor = mocker.patch.object(runner, "LlamaServer")
        out = runner.get_server(Path("/tmp/model.gguf"))
        mock_ctor.assert_not_called()
        assert out is existing

    def test_replaces_dead_server(self, mocker):
        dead = MagicMock()
        dead.proc = MagicMock()
        dead.proc.poll.return_value = 0  # dead
        runner._server = dead
        new = MagicMock()
        new.proc = None
        mocker.patch.object(runner, "LlamaServer", return_value=new)
        out = runner.get_server(Path("/tmp/model.gguf"))
        new.start.assert_called_once()
        assert out is new


class TestShutdown:
    def test_stops_and_clears_singleton(self):
        s = MagicMock()
        runner._server = s
        runner.shutdown()
        s.stop.assert_called_once()
        assert runner._server is None

    def test_noop_when_no_server(self):
        runner._server = None
        runner.shutdown()  # should not raise

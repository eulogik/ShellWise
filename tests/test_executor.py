import pytest
import os
import tempfile
from shellwise import executor
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestHandleCd:
    def test_cd_home(self):
        original_cwd = os.getcwd()
        code = executor.handle_cd("")
        assert code == 0
        assert os.getcwd() == os.path.expanduser("~")
        os.chdir(original_cwd)

    def test_cd_valid_dir(self):
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                code = executor.handle_cd(tmpdir)
                assert code == 0
                assert os.path.realpath(os.getcwd()) == os.path.realpath(tmpdir)
        finally:
            os.chdir(original_cwd)

    def test_cd_invalid_dir(self):
        code = executor.handle_cd("/nonexistent/path")
        assert code == 1

    def test_cd_permission_denied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            restricted = os.path.join(tmpdir, "restricted")
            os.mkdir(restricted)
            os.chmod(restricted, 0o000)
            try:
                code = executor.handle_cd(restricted)
                assert code == 1
            finally:
                os.chmod(restricted, 0o755)


class TestUsesShellSyntax:
    def test_pipe(self):
        assert executor._uses_shell_syntax("ls | grep foo") is True

    def test_redirect(self):
        assert executor._uses_shell_syntax("echo hello > file") is True

    def test_glob(self):
        assert executor._uses_shell_syntax("ls *.py") is True

    def test_simple_command(self):
        assert executor._uses_shell_syntax("ls -la") is False

    def test_no_shell_chars(self):
        assert executor._uses_shell_syntax("cat file.txt") is False


class TestLogging:
    def test_log_command_creates_file(self):
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            tmp_path = Path(f.name)
        try:
            original_history = executor.CMD_HISTORY
            executor.CMD_HISTORY = tmp_path
            executor._log_command("ls -la", "/test", "read")
            content = tmp_path.read_text()
            assert "ls -la" in content
            assert "/test" in content
        finally:
            executor.CMD_HISTORY = original_history
            os.unlink(tmp_path)

    def test_log_undo_creates_file(self):
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            tmp_path = Path(f.name)
        try:
            original_undo = executor.UNDO_LOG
            executor.UNDO_LOG = tmp_path
            executor._log_undo("rm file", "/test", "deletes file")
            content = tmp_path.read_text()
            assert "rm file" in content
            assert "deletes file" in content
        finally:
            executor.UNDO_LOG = original_undo
            os.unlink(tmp_path)


class TestRunPassthrough:
    def test_run_passthrough_echo(self, mocker):
        mocker.patch("subprocess.run", return_value=MagicMock(returncode=0))
        code = executor.run_passthrough("echo hello")
        assert code == 0

    def test_run_passthrough_interrupt(self, mocker):
        mocker.patch("subprocess.run", side_effect=KeyboardInterrupt)
        code = executor.run_passthrough("sleep 10")
        assert code == 130


class TestRun:
    def setup_method(self):
        self.original_cwd = os.getcwd()
        if not os.path.exists(self.original_cwd):
            os.chdir(os.path.expanduser("~"))
            self.original_cwd = os.getcwd()

    def teardown_method(self):
        os.chdir(self.original_cwd)

    def test_run_cd_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            code = executor.run(f"cd {tmpdir}", "read")
            assert code == 0
            assert os.path.realpath(os.getcwd()) == os.path.realpath(tmpdir)

    def test_run_non_interactive_command(self, mocker):
        mocker.patch("shellwise.executor.run_streaming", return_value=0)
        code = executor.run("ls -la", "read", interactive=False)
        assert code == 0

    def test_run_interactive_command(self, mocker):
        mocker.patch("shellwise.executor.run_passthrough", return_value=0)
        code = executor.run("vim", "read", interactive=True)
        assert code == 0

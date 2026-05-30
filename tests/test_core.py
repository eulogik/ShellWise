import pytest
import json
from shellwise import core
from shellwise import ai
from unittest.mock import patch, MagicMock


class TestProcessAiQuery:
    def test_empty_commands_returns_history(self, mocker):
        mocker.patch("shellwise.core.load_config", return_value={"cache_enabled": False})
        mock_query = mocker.patch("shellwise.ai.query")
        mock_query.return_value = {"commands": []}
        history, exit_sw = core.process_ai_query("test", [], dry_run=False)
        assert exit_sw is False

    def test_raw_fallback_shows_raw(self, mocker):
        mocker.patch("shellwise.core.load_config", return_value={"cache_enabled": False})
        mock_query = mocker.patch("shellwise.ai.query")
        mock_query.return_value = {"_raw": "some raw text"}
        history, exit_sw = core.process_ai_query("test", [], dry_run=False)
        assert exit_sw is False

    def test_clarification_asks_user(self, mocker):
        mocker.patch("shellwise.core.load_config", return_value={"cache_enabled": False})
        mock_query = mocker.patch("shellwise.ai.query")
        mock_query.side_effect = [
            {"clarify": "Which directory?", "options": ["src", "tests"]},
            {"commands": [{"cmd": "ls src", "type": "read", "interactive": False}]}
        ]
        mocker.patch("shellwise.display.clarify", return_value="src")
        history, exit_sw = core.process_ai_query("list files in src", [], dry_run=True)
        assert exit_sw is False

    def test_read_command_dry_run(self, mocker):
        mocker.patch("shellwise.core.load_config", return_value={"cache_enabled": False})
        mock_query = mocker.patch("shellwise.ai.query")
        mock_query.return_value = {
            "commands": [{"cmd": "ls -la", "type": "read", "interactive": False}]
        }
        mocker.patch("shellwise.executor.run", return_value=0)
        history, exit_sw = core.process_ai_query("list files", [], dry_run=True)
        assert exit_sw is False

    def test_write_command_skipped_on_dry_run(self, mocker):
        mocker.patch("shellwise.core.load_config", return_value={"cache_enabled": False})
        mock_query = mocker.patch("shellwise.ai.query")
        mock_query.return_value = {
            "commands": [{"cmd": "mkdir test", "type": "write", "interactive": False,
                         "repercussions": "creates directory"}]
        }
        mocker.patch("shellwise.display.confirm_write", return_value=False)
        mocker.patch("shellwise.executor.run", return_value=0)
        history, exit_sw = core.process_ai_query("create dir", [], dry_run=True)
        assert exit_sw is False

    def test_interactive_command_exits_sw(self, mocker):
        mocker.patch("shellwise.core.load_config", return_value={"cache_enabled": False})
        mock_query = mocker.patch("shellwise.ai.query")
        mock_query.return_value = {
            "commands": [{"cmd": "vim test.txt", "type": "read", "interactive": True}]
        }
        mocker.patch("shellwise.display.confirm_exit_sw", return_value=True)
        mocker.patch("shellwise.executor.run", return_value=0)
        history, exit_sw = core.process_ai_query("open editor", [], dry_run=True)
        assert exit_sw is True

    def test_model_error_handled(self, mocker):
        mocker.patch("shellwise.core.load_config", return_value={"cache_enabled": False})
        mock_query = mocker.patch("shellwise.ai.query")
        mock_query.side_effect = ConnectionError("Model not available")
        history, exit_sw = core.process_ai_query("test", [], dry_run=False)
        assert exit_sw is False

    def test_catastrophic_blocked(self, mocker):
        mocker.patch("shellwise.core.load_config", return_value={"cache_enabled": False})
        mock_query = mocker.patch("shellwise.ai.query")
        mock_query.return_value = {
            "commands": [{"cmd": "rm -rf /", "type": "critical", "interactive": False,
                         "repercussions": "deletes everything"}]
        }
        history, exit_sw = core.process_ai_query("delete everything", [], dry_run=False)
        assert exit_sw is False


class TestProcessShellCommand:
    def test_empty_command_returns_false(self):
        result = core.process_shell_command("  ", dry_run=False)
        assert result is False

    def test_read_command_runs(self, mocker):
        mocker.patch("shellwise.executor.run", return_value=0)
        result = core.process_shell_command("ls -la", dry_run=False)
        assert result is False

    def test_tui_command_prompts_exit(self, mocker):
        mocker.patch("shellwise.ai.cmd_is_tui", return_value=True)
        mocker.patch("shellwise.display.confirm_exit_sw", return_value=True)
        mocker.patch("shellwise.executor.run", return_value=0)
        result = core.process_shell_command("vim", dry_run=False)
        assert result is True

    def test_tui_command_skipped(self, mocker):
        mocker.patch("shellwise.ai.cmd_is_tui", return_value=True)
        mocker.patch("shellwise.display.confirm_exit_sw", return_value=False)
        result = core.process_shell_command("vim", dry_run=False)
        assert result is False

    def test_dry_run_skips_execution(self, mocker):
        mock_run = mocker.patch("shellwise.executor.run")
        result = core.process_shell_command("ls", dry_run=True)
        mock_run.assert_not_called()
        assert result is False


class TestProcessInput:
    def test_direct_command_routes_to_shell(self, mocker):
        mocker.patch("shellwise.ai.strip_ai_prefix", return_value=(False, "ls -la"))
        mocker.patch("shellwise.ai.should_execute_directly", return_value=True)
        mock_shell = mocker.patch("shellwise.core.process_shell_command", return_value=False)
        history, exit_sw = core.process_input("ls -la", [])
        mock_shell.assert_called_once()
        assert exit_sw is False

    def test_natural_language_routes_to_ai(self, mocker):
        mocker.patch("shellwise.ai.strip_ai_prefix", return_value=(False, "list files"))
        mocker.patch("shellwise.ai.should_execute_directly", return_value=False)
        mock_ai = mocker.patch("shellwise.core.process_ai_query", return_value=([], False))
        history, exit_sw = core.process_input("list files", [])
        mock_ai.assert_called_once()
        assert exit_sw is False

    def test_ai_prefix_forces_ai(self, mocker):
        mocker.patch("shellwise.ai.strip_ai_prefix", return_value=(True, "ls -la"))
        mocker.patch("shellwise.ai.should_execute_directly", return_value=True)
        mock_ai = mocker.patch("shellwise.core.process_ai_query", return_value=([], False))
        history, exit_sw = core.process_input("ai ls -la", [])
        mock_ai.assert_called_once()

    def test_error_recovery(self, mocker):
        mocker.patch("shellwise.ai.strip_ai_prefix", side_effect=RuntimeError("fail"))
        history, exit_sw = core.process_input("test", [])
        assert exit_sw is False
        assert history == []

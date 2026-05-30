import pytest
from shellwise import ai


class TestCmdIsTui:
    def test_vim_is_tui(self):
        assert ai.cmd_is_tui("vim") is True

    def test_vim_with_args_is_tui(self):
        assert ai.cmd_is_tui("vim README.md") is True

    def test_ssh_is_tui(self):
        assert ai.cmd_is_tui("ssh user@host") is True

    def test_ls_is_not_tui(self):
        assert ai.cmd_is_tui("ls") is False

    def test_python_repl_is_tui(self):
        assert ai.cmd_is_tui("python") is True

    def test_python_script_is_not_tui(self):
        assert ai.cmd_is_tui("python script.py") is False

    def test_empty_command(self):
        assert ai.cmd_is_tui("") is False

    def test_bash_is_tui(self):
        assert ai.cmd_is_tui("bash") is True

    def test_tmux_is_tui(self):
        assert ai.cmd_is_tui("tmux") is True

    def test_htop_is_tui(self):
        assert ai.cmd_is_tui("htop") is True

    def test_less_is_tui(self):
        assert ai.cmd_is_tui("less file.log") is True

    def test_man_is_tui(self):
        assert ai.cmd_is_tui("man ls") is True


class TestShouldExecuteDirectly:
    def test_ls_exists(self):
        assert ai.should_execute_directly("ls -la") is True

    def test_git_exists(self):
        assert ai.should_execute_directly("git status") is True

    def test_cd_builtin(self):
        assert ai.should_execute_directly("cd /tmp") is True

    def test_nonsense_not_direct(self):
        assert ai.should_execute_directly("list all the files here") is False

    def test_empty_not_direct(self):
        assert ai.should_execute_directly("") is False


class TestStripAiPrefix:
    def test_ai_prefix_stripped(self):
        force, value = ai.strip_ai_prefix("ai list files")
        assert force is True
        assert value == "list files"

    def test_no_prefix(self):
        force, value = ai.strip_ai_prefix("list files")
        assert force is False
        assert value == "list files"

    def test_ai_prefix_case_insensitive(self):
        force, value = ai.strip_ai_prefix("AI list files")
        assert force is True
        assert value == "list files"

    def test_ai_prefix_with_spaces(self):
        force, value = ai.strip_ai_prefix("  ai  list files  ")
        assert force is True
        assert value == "list files"


class TestQueryMock:
    def test_query_returns_dict(self, mocker):
        mock_query = mocker.patch("shellwise.ai.mdl.query")
        mock_query.return_value = '{"commands": [{"cmd": "ls", "type": "read", "interactive": false}]}'
        result = ai.query("list files", [])
        assert isinstance(result, dict)
        assert "commands" in result

    def test_query_invalid_json_returns_raw(self, mocker):
        mock_query = mocker.patch("shellwise.ai.mdl.query")
        mock_query.return_value = "invalid json"
        result = ai.query("test", [])
        assert "_raw" in result

    def test_query_normalizes_du_command(self, mocker):
        mock_query = mocker.patch("shellwise.ai.mdl.query")
        mock_query.return_value = '{"commands": [{"cmd": "du -sh ./*", "type": "read", "interactive": false}]}'
        result = ai.query("sizes of dirs", [])
        assert result["commands"][0]["cmd"] == "du -sh *"

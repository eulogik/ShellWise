import pytest
from shellwise import display
from unittest.mock import patch


class TestColorFunctions:
    def test_dim_returns_text(self):
        result = display.dim("test")
        assert "test" in result

    def test_bold_returns_text(self):
        result = display.bold("test")
        assert "test" in result

    def test_green_returns_text(self):
        result = display.green("test")
        assert "test" in result

    def test_yellow_returns_text(self):
        result = display.yellow("test")
        assert "test" in result

    def test_red_returns_text(self):
        result = display.red("test")
        assert "test" in result


class TestPrompt:
    def test_sw_prompt_returns_string(self):
        result = display.sw_prompt("/Users/test")
        assert isinstance(result, str)
        assert "sw" in result

    def test_sw_prompt_handles_empty_cwd(self):
        result = display.sw_prompt("")
        assert isinstance(result, str)

    def test_sw_prompt_includes_git_branch(self, mocker):
        mocker.patch("shellwise.display._git_branch", return_value="main")
        result = display.sw_prompt("/Users/test")
        assert "main" in result

    def test_sw_prompt_no_branch(self, mocker):
        mocker.patch("shellwise.display._git_branch", return_value="")
        result = display.sw_prompt("/Users/test")
        assert "(" not in result


class TestCommandDisplay:
    def test_show_write_command(self):
        display.show_write_command("rm file", "deletes file")

    def test_show_critical_command(self):
        display.show_critical_command("dd if=/dev/zero of=/dev/sdb", "wipes disk")

    def test_show_blocked(self):
        display.show_blocked("rm -rf /", "catastrophic")


class TestConfirmations:
    def test_confirm_write_yes(self, mocker):
        mocker.patch("builtins.input", return_value="y")
        assert display.confirm_write("rm file") is True

    def test_confirm_write_no(self, mocker):
        mocker.patch("builtins.input", return_value="n")
        assert display.confirm_write("rm file") is False

    def test_confirm_write_default(self, mocker):
        mocker.patch("builtins.input", return_value="")
        assert display.confirm_write("rm file") is True

    def test_confirm_critical_yes(self, mocker):
        mocker.patch("builtins.input", return_value="YES")
        assert display.confirm_critical("dd") is True

    def test_confirm_critical_no(self, mocker):
        mocker.patch("builtins.input", return_value="no")
        assert display.confirm_critical("dd") is False

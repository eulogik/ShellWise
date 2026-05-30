import pytest
from shellwise import classifier


class TestIsCatastrophic:
    def test_rm_rf_root(self):
        assert classifier.is_catastrophic("rm -rf /") is True

    def test_rm_rf_star(self):
        assert classifier.is_catastrophic("rm -rf /*") is True

    def test_rm_rf_home(self):
        assert classifier.is_catastrophic("rm -rf ~") is True

    def test_rm_rf_boot(self):
        assert classifier.is_catastrophic("rm -rf /boot") is True

    def test_dd_overwrite_disk(self):
        assert classifier.is_catastrophic("dd if=/dev/zero of=/dev/sda") is True

    def test_mkfs_disk(self):
        assert classifier.is_catastrophic("mkfs.ext4 /dev/sda") is True

    def test_fork_bomb(self):
        assert classifier.is_catastrophic(":(){ :|:& };:") is True

    def test_sudo_rm(self):
        assert classifier.is_catastrophic("sudo rm -rf /tmp/test") is True

    def test_safe_rm(self):
        assert classifier.is_catastrophic("rm file.txt") is False

    def test_safe_ls(self):
        assert classifier.is_catastrophic("ls -la") is False

    def test_empty(self):
        assert classifier.is_catastrophic("") is False


class TestClassifyCommand:
    def test_ls_is_read(self):
        assert classifier.classify_command("ls -la") == "read"

    def test_cat_is_read(self):
        assert classifier.classify_command("cat file.txt") == "read"

    def test_grep_is_read(self):
        assert classifier.classify_command("grep pattern file") == "read"

    def test_du_is_read(self):
        assert classifier.classify_command("du -sh *") == "read"

    def test_find_read(self):
        assert classifier.classify_command("find . -name '*.py'") == "read"

    def test_find_write(self):
        assert classifier.classify_command("find . -name '*.log' -delete") == "write"

    def test_mkdir_is_write(self):
        assert classifier.classify_command("mkdir test") == "write"

    def test_cp_is_write(self):
        assert classifier.classify_command("cp src dest") == "write"

    def test_touch_is_write(self):
        assert classifier.classify_command("touch newfile") == "write"

    def test_rm_is_write(self):
        assert classifier.classify_command("rm file.txt") == "write"

    def test_curl_get_is_read(self):
        assert classifier.classify_command("curl https://example.com") == "read"

    def test_curl_post_is_write(self):
        assert classifier.classify_command("curl -X POST https://api.com") == "write"

    def test_curl_with_data_is_write(self):
        assert classifier.classify_command("curl -d 'data' https://api.com") == "write"

    def test_git_status_is_read(self):
        assert classifier.classify_command("git status") == "read"

    def test_git_log_is_read(self):
        assert classifier.classify_command("git log --oneline") == "read"

    def test_git_commit_is_write(self):
        assert classifier.classify_command("git commit -m 'fix'") == "write"

    def test_git_push_is_write(self):
        assert classifier.classify_command("git push origin main") == "write"

    def test_write_redirection(self):
        assert classifier.classify_command("echo hello > file.txt") == "write"

    def test_append_redirection(self):
        assert classifier.classify_command("echo hello >> file.txt") == "write"

    def test_chained_commands(self):
        assert classifier.classify_command("ls && cat file") == "write"

    def test_pipe_tee(self):
        assert classifier.classify_command("ls | tee output.txt") == "write"

    def test_catastrophic_is_critical(self):
        assert classifier.classify_command("rm -rf /") == "critical"

    def test_unknown_defaults_to_write(self):
        assert classifier.classify_command("someunknowncommand") == "write"

    def test_empty_defaults_to_write(self):
        assert classifier.classify_command("") == "write"


class TestHasWriteRedirection:
    def test_simple_redirect(self):
        assert classifier.has_write_redirection("echo > file") is True

    def test_append_redirect(self):
        assert classifier.has_write_redirection("echo >> file") is True

    def test_tee_pipe(self):
        assert classifier.has_write_redirection("ls | tee file") is True

    def test_no_redirect(self):
        assert classifier.has_write_redirection("ls -la") is False


class TestHasChainedCommands:
    def test_and_chain(self):
        assert classifier.has_chained_commands("ls && cat file") is True

    def test_or_chain(self):
        assert classifier.has_chained_commands("cmd1 || cmd2") is True

    def test_semicolon_chain(self):
        assert classifier.has_chained_commands("ls; cat file") is True

    def test_no_chain(self):
        assert classifier.has_chained_commands("ls -la") is False

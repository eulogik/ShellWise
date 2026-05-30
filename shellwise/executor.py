"""
shellwise.executor
Runs shell commands, streams output, handles special cases:
  - cd must use os.chdir() to affect the current process
  - interactive commands (vi, ssh, top) need direct terminal access
  - undo logging for write/critical commands
  - safe execution: arg arrays for simple commands, shell for pipes/globs
"""

import fcntl
import os
import re
import shlex
import sys
import subprocess
from pathlib import Path
from datetime import datetime

UNDO_LOG = Path.home() / ".shellwise" / "undo.log"
CMD_HISTORY = Path.home() / ".shellwise" / "history"


def _log_command(cmd: str, cwd: str, cmd_type: str):
    """Append executed command to history file with file locking."""
    CMD_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(CMD_HISTORY, "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(f"{timestamp}\t{cwd}\t{cmd}\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _log_undo(cmd: str, cwd: str, repercussions: str):
    """Log write/critical commands with reversal hints to undo log with file locking."""
    UNDO_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(UNDO_LOG, "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(f"\n[{timestamp}]\n")
            f.write(f"  cwd: {cwd}\n")
            f.write(f"  cmd: {cmd}\n")
            f.write(f"  impact: {repercussions}\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def handle_cd(args: str) -> int:
    """Handle cd in the current process."""
    target = args.strip() or str(Path.home())
    target = os.path.expanduser(target)
    target = os.path.expandvars(target)
    try:
        os.chdir(target)
        return 0
    except FileNotFoundError:
        print(f"  cd: no such file or directory: {target}")
        return 1
    except PermissionError:
        print(f"  cd: permission denied: {target}")
        return 1


def _uses_shell_syntax(cmd: str) -> bool:
    """Check if command needs shell interpretation (pipes, globs, redirects)."""
    return bool(re.search(r'[|&;<>*?~()\[\]{}$`]', cmd))


def run_passthrough(cmd: str) -> int:
    """
    Run a command with full terminal access (for interactive commands).
    Blocks until the command exits.
    """
    try:
        result = subprocess.run(cmd, shell=True)
        return result.returncode
    except KeyboardInterrupt:
        return 130


def run_streaming(cmd: str) -> int:
    """
    Run a non-interactive command, stream stdout and stderr separately.
    Uses safe arg-array execution for simple commands, shell for complex ones.
    """
    try:
        if _uses_shell_syntax(cmd):
            # Needs shell for pipes, globs, redirects
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        else:
            # Safe: arg array, no shell injection
            argv = shlex.split(cmd)
            if not argv:
                return 1
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

        # Stream stdout
        if proc.stdout:
            for line in proc.stdout:
                sys.stdout.write("  " + line)
                sys.stdout.flush()
        # Stream stderr
        if proc.stderr:
            for line in proc.stderr:
                sys.stderr.write(f"  [err] {line}")
                sys.stderr.flush()
        proc.wait()
        return proc.returncode
    except KeyboardInterrupt:
        proc.terminate()
        return 130
    except Exception as e:
        print(f"  execution error: {e}")
        return 1


def run(cmd: str, cmd_type: str = "read",
        interactive: bool = False,
        repercussions: str = "") -> int:
    """
    Main entry point for command execution.
    Returns exit code.
    """
    cwd = os.getcwd()

    # handle cd specially
    stripped = cmd.strip()
    if stripped == "cd" or stripped.startswith("cd ") or stripped.startswith("cd\t"):
        args = stripped[2:].strip()
        code = handle_cd(args)
        _log_command(cmd, cwd, cmd_type)
        return code

    # log to history
    _log_command(cmd, cwd, cmd_type)

    # log undo info for write/critical
    if cmd_type in ("write", "critical") and repercussions:
        _log_undo(cmd, cwd, repercussions)

    if interactive:
        return run_passthrough(cmd)
    else:
        return run_streaming(cmd)

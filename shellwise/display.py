"""
shellwise.display
All terminal output — banner, colors, command display, confirmations.
"""

from __future__ import annotations

import sys
import os
import shutil
import subprocess
import textwrap

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

def _term_width():
    return shutil.get_terminal_size((80, 24)).columns

from . import __version__
VERSION = __version__

def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

def dim(t):        return _c("2", t)
def bold(t):       return _c("1", t)
def green(t):      return _c("32", t)
def yellow(t):     return _c("33", t)
def red(t):        return _c("31", t)
def cyan(t):       return _c("36", t)
def blue(t):       return _c("34", t)
def white(t):      return _c("97", t)
def magenta(t):    return _c("35", t)
def bg_red(t):     return _c("41;97;1", t)
def bg_yellow(t):  return _c("43;30;1", t)
def bg_green(t):   return _c("42;30;1", t)
def bg_blue(t):    return _c("44;97", t)


# ── Banner ────────────────────────────────────────────────────────────────────

BANNER = r"""
      ┌──────────────────────────────────────────────────────────┐
      │                                                          │
   ███████╗██╗  ██╗███████╗██╗     ██╗     ██╗    ██╗██╗███████╗███████╗
   ██╔════╝██║  ██║██╔════╝██║     ██║     ██║    ██║██║██╔════╝██╔════╝
   ███████╗███████║█████╗  ██║     ██║     ██║ █╗ ██║██║███████╗█████╗
   ╚════██║██╔══██║██╔══╝  ██║     ██║     ██║███╗██║██║╚════██║██╔══╝
   ███████║██║  ██║███████╗███████╗███████╗╚███╔███╔╝██║███████║███████╗
   ╚══════╝╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝ ╚══╝╚══╝ ╚═╝╚══════╝╚══════╝
      │                                                          │
      └──────────────────────────────────────────────────────────┘
"""

def banner():
    print(cyan(BANNER))
    print(f"  {bold('shellwise')} {dim('v' + VERSION)}  —  your local AI terminal co-pilot\n")
    print(f"  {dim('─' * 56)}\n")
    print(f"  {bold('How to use:')}")
    print(f"  {dim('·')} type any {cyan('shell command')}        → runs directly")
    print(f"  {dim('·')} type in {yellow('plain English')}        → AI generates & runs it")
    print(f"  {dim('·')} prefix with {magenta('ai ')}             → force AI mode")
    print(f"  {dim('·')} {bold('sw --explain')} {dim('<cmd>')}      → explain a command")
    print(f"  {dim('·')} type {red('exit')} or {red('Ctrl+D')}         → leave sw mode")
    print(f"\n  {dim('─' * 56)}\n")


def header():
    """Compact header for one-shot mode."""
    print()
    print(f"  {bold(cyan('shellwise'))} {dim('·')} local AI terminal co-pilot")
    print(f"  {dim('─' * 42)}")
    print()


# ── Prompt ───────────────────────────────────────────────────────────────────

def _git_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0 and result.stdout.strip():
            branch = result.stdout.strip()
            # Check dirty
            dirty = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=1
            )
            if dirty.returncode == 0 and dirty.stdout.strip():
                return f"{branch}*"
            return branch
    except (subprocess.TimeoutExpired, OSError):
        pass
    return ""


def sw_prompt(cwd: str = "") -> str:
    short_cwd = cwd.replace(os.path.expanduser("~"), "~") if cwd else ""
    branch = _git_branch()
    branch_str = f" {green('(' + branch + ')')}" if branch else ""
    return f"  {dim(short_cwd)}{branch_str} {cyan('sw')} {dim('›')} "


# ── Command display ───────────────────────────────────────────────────────────

def show_write_command(cmd: str, repercussions: str):
    print(f"\n  {dim('$')} {bold(yellow(cmd))}")
    print(f"  {bg_yellow(' impact ')} {repercussions}")


def show_critical_command(cmd: str, repercussions: str):
    print(f"\n  {dim('$')} {bold(red(cmd))}")
    print(f"  {bg_red(' WARNING ')} {repercussions}")


def show_blocked(cmd: str, repercussions: str):
    print(f"\n  {bg_red(' BLOCKED ')} {bold(red(cmd))}")
    print(f"  {red('This command is locally blocked for safety.')}")
    if repercussions:
        print(f"  {dim('reason: ' + repercussions)}")


def show_multi_plan(commands: list):
    print(f"\n  {dim('plan — ' + str(len(commands)) + ' step' + ('s' if len(commands) != 1 else ''))}")
    for i, c in enumerate(commands, 1):
        t   = c.get("type", "read")
        cmd = c.get("cmd", "")
        itv = c.get("interactive", False)
        blocked = c.get("_blocked", False)
        if blocked:
            color = red
            tag = "BLOCKED"
        elif t == "critical":
            color = red
            tag = t
        elif t == "write":
            color = yellow
            tag = t
        else:
            color = dim
            tag = t
        color_tag = color(f"[{tag}]")
        ivtag = magenta(" [interactive]") if itv else ""
        print(f"  {dim(str(i) + '.')} {color_tag}{ivtag} {bold(cmd)}")
    print()


# ── Execution feedback ────────────────────────────────────────────────────────

def show_result(exit_code: int):
    if exit_code == 0:
        print(f"  {bg_green(' done ')}\n")
    elif exit_code == 130:
        print(f"  {dim('interrupted')}\n")
    else:
        print(f"  {bg_red(' error ')} exit {exit_code}\n")


def show_skipped():
    print(f"  {dim('skipped.')}\n")


# ── Confirmations ─────────────────────────────────────────────────────────────

def confirm_write(cmd: str) -> bool:
    try:
        ans = input(f"\n  run this? {dim('[Y/n]')} ").strip().lower()
        return ans in ("", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def confirm_critical(cmd: str) -> bool:
    print(f"\n  {red('This action may be irreversible.')}")
    try:
        ans = input(f"  type {bold(red('YES'))} to confirm: ").strip()
        return ans == "YES"
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def confirm_exit_sw(reason: str) -> bool:
    """Ask user if they want to exit sw mode to run an interactive command."""
    print(f"\n  {bg_blue(' sw mode ')} {reason}")
    print(f"  This command will take over the terminal.")
    try:
        ans = input(f"  exit sw mode and run it? {dim('[Y/n]')} ").strip().lower()
        return ans in ("", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


# ── Clarification ─────────────────────────────────────────────────────────────

def clarify(question: str, options: list) -> str:
    print(f"\n  {cyan('?')} {question}")
    for i, opt in enumerate(options, 1):
        print(f"    {dim(str(i) + '.')} {opt}")
    print()
    try:
        return input("  answer: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


# ── Explain mode ──────────────────────────────────────────────────────────────

def show_explanation(cmd: str, explanation: str):
    print(f"\n  {dim('explaining:')} {bold(white(cmd))}\n")
    wrapped = textwrap.fill(explanation, width=min(_term_width() - 4, 76),
                            initial_indent="  ", subsequent_indent="  ")
    print(cyan(wrapped))
    print()


# ── Errors / misc ─────────────────────────────────────────────────────────────

def show_error(msg: str):
    for line in msg.strip().splitlines():
        print(f"  {red('·')} {line}")
    print()


def show_raw(text: str):
    print(f"\n  {dim(text)}\n")


def show_history_saved(path: str):
    print(f"  {dim('history → ' + path)}")


def thinking():
    sys.stdout.write(f"  {dim('thinking...')}")
    sys.stdout.flush()


def clear_thinking():
    sys.stdout.write("\r" + " " * 20 + "\r")
    sys.stdout.flush()

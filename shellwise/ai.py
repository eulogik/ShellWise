"""
shellwise.ai
Builds prompts, queries the model, parses responses.
Injects rich system context (OS, distro, cwd, ls, git, pkg manager).
"""

from __future__ import annotations

import functools
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from . import model as mdl
from . import classifier

# ── System context ────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def _static_context() -> str:
    """Cache the parts of context that don't change during runtime."""
    info = {
        "os": platform.system(),
        "arch": platform.machine(),
    }
    # distro detection
    if platform.system() == "Linux":
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        info["distro"] = line.split("=", 1)[1].strip().strip('"')
                        break
        except FileNotFoundError:
            pass
        for pm in ["apt", "dnf", "pacman", "zypper", "apk"]:
            if subprocess.run(["which", pm], capture_output=True).returncode == 0:
                info["pkg_manager"] = pm
                break
    elif platform.system() == "Darwin":
        info["distro"] = "macOS " + platform.mac_ver()[0]
        info["pkg_manager"] = "brew" if subprocess.run(
            ["which", "brew"], capture_output=True).returncode == 0 else None
    return ", ".join(f"{k}: {v}" for k, v in info.items() if v)


def _system_context() -> str:
    """Build full context — static parts cached, dynamic parts fresh."""
    parts = [_static_context(), f"cwd: {os.getcwd()}"]

    # ls output for context
    try:
        result = subprocess.run(
            ["ls", "-la"], capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            lines = result.stdout.strip().splitlines()[:50]
            parts.append("ls:\n" + "\n".join(lines))
    except (subprocess.TimeoutExpired, OSError):
        pass

    # git branch
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            parts.append(f"git_branch: {result.stdout.strip()}")
    except (subprocess.TimeoutExpired, OSError):
        pass

    return ", ".join(parts)


SYSTEM_PROMPT_TEMPLATE = """You are a Linux/Unix shell command expert embedded in a safety-aware CLI tool called shellwise.

System context: {context}

Respond ONLY with a valid JSON object — no prose, no markdown fences, no extra text.

Schema:
{{
  "commands": [
    {{
      "cmd": "the complete shell command with all arguments",
      "type": "read|write|critical",
      "repercussions": "one honest sentence about system impact (omit for read commands)",
      "interactive": true/false
    }}
  ],
  "note": "optional one-liner tip — omit if nothing useful to add"
}}

Classification:
- "read"     → zero side effects: ls, cat, df, ps, find (no -delete), grep, du, etc.
- "write"    → modifies state: cp, mv, mkdir, chmod, apt install, pip install, etc.
- "critical" → destructive or irreversible: rm, dd, mkfs, shred, kill -9, etc.

interactive: true  → command takes over the terminal (vi, nano, ssh, tmux, etc.)
interactive: false → command runs and exits on its own

If the request is ambiguous, respond with:
{{ "clarify": "one short question", "options": ["option 1", "option 2", ...] }}

Rules:
- Multi-step tasks → multiple objects in commands array, in order
- Never add sudo unless user explicitly asked
- Use the system's package manager ({pkg_manager}) for install commands
- repercussions must be present for write and critical, absent for read
- Keep repercussions honest and specific — not vague filler
- interactive field is always required
- For directory size summaries, use `du -sh *` NOT `du -sh ./*`
- Prefer direct commands over brittle parsing pipelines
- ALWAYS include all required arguments — never output incomplete commands like `touch` without a filename
- If creating a file, include the filename: `touch newfile.txt` not just `touch`
- If opening an editor, include the file: `vi newfile.txt` not just `vi`
"""

# ── Shell command detection (which-based) ─────────────────────────────────────

BUILTIN_COMMANDS = {"cd", "exit", "export", "alias", "unalias", "source",
                    "eval", "exec", "shift", "set", "unset", "local",
                    "readonly", "declare", "typeset", "return", "break",
                    "continue", "trap", "wait", "kill", "bg", "fg", "jobs",
                    "pushd", "popd", "dirs", "hash", "history", "fc",
                    "bind", "compgen", "complete", "compopt", "enable",
                    "help", "let", "mapfile", "readarray", "read", "shopt",
                    "times", "type", "ulimit", "umask"}


def _command_exists(cmd: str) -> bool:
    """Check if a command exists on PATH or is a shell builtin.

    Uses shutil.which (which is portable and doesn't depend on
    `command` being a real binary — `command` is a shell builtin on
    Linux but a real binary on macOS, so subprocess.run([...])
    would raise FileNotFoundError on Ubuntu).
    """
    if cmd.lower() in BUILTIN_COMMANDS:
        return True
    return shutil.which(cmd) is not None


def should_execute_directly(text: str) -> bool:
    """
    Determine if input should run as a direct shell command.
    Returns True if the first token is a known command on PATH.
    """
    stripped = text.strip()
    if not stripped:
        return False
    first_word = stripped.split()[0].lstrip("./")
    return _command_exists(first_word)


def strip_ai_prefix(text: str) -> tuple:
    """Strip 'ai ' prefix to force AI mode. Returns (force_ai, value)."""
    stripped = text.strip()
    if re.match(r"^ai\s+", stripped, re.IGNORECASE):
        return True, stripped[2:].strip()
    return False, stripped


# ── Interactive command detection ─────────────────────────────────────────────

TUI_COMMANDS = {
    "vi", "vim", "nvim", "nano", "emacs", "pico", "joe",
    "top", "htop", "btop", "iotop", "atop", "watch",
    "less", "more", "man",
    "ssh", "telnet", "ftp", "sftp",
    "screen", "tmux", "byobu",
    "gdb", "lldb",
    "mutt", "pine", "alpine",
    "fzf", "tig", "lazygit", "ranger", "lf",
    "mysql", "psql", "sqlite3", "mongo", "redis-cli",
}


def cmd_is_tui(cmd: str) -> bool:
    """Check if command is a full-screen TUI app that needs terminal takeover."""
    first = cmd.strip().split()[0] if cmd.strip() else ""
    if first.lower() in TUI_COMMANDS:
        return True
    # REPLs with no args are TUI
    if first.lower() in ("python", "python3", "node", "irb", "ruby", "julia", "lua", "php"):
        if cmd.strip().lower() == first.lower():
            return True
    # Shell sessions
    if first.lower() in ("bash", "zsh", "fish", "sh"):
        return True
    return False


# ── Main query function ───────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    ctx = _system_context()
    pkg = "apt/dnf/brew (auto-detected)"
    for part in ctx.split(", "):
        if part.startswith("pkg_manager:"):
            pkg = part.split(":", 1)[1].strip()
    return SYSTEM_PROMPT_TEMPLATE.format(context=ctx, pkg_manager=pkg)


def _normalize_command(cmd: str) -> str:
    """Normalize generated commands (e.g., du -sh ./* → du -sh *)."""
    trimmed = cmd.strip()
    if re.match(r"^du\s+-sh\b", trimmed, re.IGNORECASE):
        trimmed = trimmed.replace("./", "", 1)
    return trimmed


def query(user_input: str, history: list) -> dict:
    """Send query to model, return parsed dict."""
    messages = [{"role": "system", "content": _build_system_prompt()}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_input})

    raw = mdl.query(messages)

    # strip markdown code blocks
    clean = re.sub(r'^```(?:bash|json|shell)?\s*', '', raw.strip(), flags=re.IGNORECASE)
    clean = re.sub(r'\s*```$', '', clean).strip()

    # sometimes model outputs extra text before the JSON — find first {
    brace = clean.find("{")
    if brace > 0:
        clean = clean[brace:]

    # If no JSON found, try to extract command from markdown
    if "{" not in clean:
        # Check for bash code block with a command
        cmd_match = re.search(r'```(?:bash|shell)?\s*\n(.+?)\n```', raw, re.DOTALL)
        if cmd_match:
            cmd = cmd_match.group(1).strip()
            if cmd:
                return {
                    "commands": [{
                        "cmd": cmd,
                        "type": "write",
                        "repercussions": "Creates or modifies files",
                        "interactive": cmd_is_tui(cmd)
                    }]
                }
        return {"_raw": raw}

    try:
        result = json.loads(clean)
        # Normalize commands
        if "commands" in result and isinstance(result["commands"], list):
            for step in result["commands"]:
                if isinstance(step, dict) and "cmd" in step:
                    step["cmd"] = _normalize_command(step["cmd"])
        return result
    except json.JSONDecodeError:
        return {"_raw": raw}


def explain(cmd: str) -> str:
    """Explain what a shell command does in plain English."""
    messages = [
        {"role": "system", "content": (
            "You are a shell expert. When given a shell command, explain clearly "
            "what it does in 2-4 sentences of plain English. No JSON. No markdown. "
            "Be specific about flags and what each part does."
        )},
        {"role": "user", "content": f"Explain this command: {cmd}"}
    ]
    return mdl.query(messages)

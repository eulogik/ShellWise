"""
shellwise.core
Shared processing logic used by both one-shot and sw interactive modes.
Features:
- Direct command execution for known commands
- AI translation for natural language
- Local safety classification (overrides AI)
- Response caching with TTL
- TUI handoff detection
- Error recovery (never crashes the loop)
"""

import json
import os
from . import ai, display, executor, classifier
from .cache import cache_get, cache_set
from .config import load_config


def _is_valid_command(cmd: str) -> bool:
    """Check if a command is complete (has required arguments)."""
    if not cmd:
        return False
    parts = cmd.split()
    if not parts:
        return False
    base = parts[0].lower()
    # Commands that require at least one argument
    requires_args = {
        "touch", "vi", "vim", "nvim", "nano", "emacs", "code",
        "cat", "less", "more", "head", "tail", "rm", "mv", "cp",
        "mkdir", "rmdir", "chmod", "chown", "ln", "grep", "find",
        "ssh", "scp", "rsync", "tar", "git", "docker", "kubectl",
        "pip", "npm", "yarn", "brew", "apt", "curl", "wget",
    }
    if base in requires_args and len(parts) < 2:
        return False
    return True


def _reclassify_steps(commands: list) -> list:
    """Re-classify all commands using local safety rules."""
    for step in commands:
        if not isinstance(step, dict):
            continue
        cmd = step.get("cmd", "")
        local_type = classifier.classify_command(cmd)
        # Local classification overrides AI
        step["type"] = local_type
        # If locally classified as critical, hard-block
        if local_type == "critical":
            step["_blocked"] = True
    return commands


def process_ai_query(user_input: str, history: list, dry_run: bool = False) -> tuple:
    """
    Send natural language to AI, display results, execute.
    Returns (updated_history, exit_sw: bool)
    exit_sw=True means the user confirmed exiting sw mode for an interactive cmd.
    """
    config = load_config()
    cwd = os.getcwd()

    # Check cache first
    cached = None
    if config.get("cache_enabled", True):
        cached = cache_get(cwd, user_input)

    if cached:
        result = cached
    else:
        display.thinking()
        try:
            result = ai.query(user_input, history)
        except ConnectionError as e:
            display.clear_thinking()
            display.show_error(str(e))
            return history, False
        except Exception as e:
            display.clear_thinking()
            display.show_error(f"Model error: {e}")
            return history, False
        display.clear_thinking()

        # Cache the response
        if config.get("cache_enabled", True) and "_raw" not in result:
            cache_set(cwd, user_input, result)

    # raw fallback
    if "_raw" in result:
        display.show_raw(result["_raw"])
        return history, False

    # clarification needed
    if "clarify" in result:
        answer = display.clarify(result["clarify"], result.get("options", []))
        if answer:
            history.append({"role": "assistant", "content": json.dumps(result)})
            history.append({"role": "user", "content": answer})
            return process_ai_query(answer, history, dry_run)
        return history, False

    commands = result.get("commands", [])
    note = result.get("note", "")

    if not commands:
        display.show_raw("No commands returned.")
        return history, False

    # Re-classify using local safety rules
    commands = _reclassify_steps(commands)

    # Filter out empty or invalid commands
    commands = [c for c in commands if _is_valid_command(c.get("cmd", ""))]

    if not commands:
        display.show_raw("Couldn't generate a valid command. Try rephrasing.")
        return history, False

    # show plan for multi-step
    if len(commands) > 1:
        display.show_multi_plan(commands)

    for i, step in enumerate(commands):
        cmd = step.get("cmd", "").strip()
        typ = step.get("type", "read")
        reps = step.get("repercussions", "")
        # Local TUI detection overrides AI's interactive field
        is_tui = ai.cmd_is_tui(cmd)
        is_blocked = step.get("_blocked", False)

        if not cmd:
            continue

        # ── Hard-blocked (catastrophic) ───────────────────────────────────
        if is_blocked:
            display.show_blocked(cmd, reps)
            display.show_skipped()
            return history, False

        # ── TUI command handling ──────────────────────────────────────────
        if is_tui:
            reason = f"'{cmd.split()[0]}' is an interactive terminal app."
            if display.confirm_exit_sw(reason):
                if not dry_run:
                    executor.run(cmd, typ, interactive=True, repercussions=reps)
                return history, True   # exit sw mode
            else:
                display.show_skipped()
                continue

        # ── Read ──────────────────────────────────────────────────────────
        if typ == "read":
            if not dry_run:
                code = executor.run(cmd, typ)
                if code != 0:
                    break

        # ── Write ─────────────────────────────────────────────────────────
        elif typ == "write":
            display.show_write_command(cmd, reps)
            if dry_run or not display.confirm_write(cmd):
                display.show_skipped()
                continue
            code = executor.run(cmd, typ, repercussions=reps)
            if code != 0:
                break

        # ── Critical ──────────────────────────────────────────────────────
        elif typ == "critical":
            display.show_critical_command(cmd, reps)
            if dry_run or not display.confirm_critical(cmd):
                display.show_skipped()
                continue
            code = executor.run(cmd, typ, repercussions=reps)
            if code != 0:
                break

    history.append({"role": "assistant", "content": json.dumps(result)})
    return history, False


def process_shell_command(cmd: str, dry_run: bool = False) -> bool:
    """
    Directly execute a shell command (passthrough from sw mode).
    Returns True if we should exit sw mode (TUI command confirmed).
    """
    stripped = cmd.strip()
    if not stripped:
        return False

    # detect TUI
    if ai.cmd_is_tui(stripped):
        reason = f"'{stripped.split()[0]}' is an interactive terminal app."
        if display.confirm_exit_sw(reason):
            if not dry_run:
                executor.run(stripped, "read", interactive=True)
            return True
        else:
            display.show_skipped()
            return False

    if not dry_run:
        executor.run(stripped, "read")
    return False


def process_input(line: str, history: list, dry_run: bool = False) -> tuple:
    """
    Process a single line of input in sw mode.
    Routes to direct execution, AI translation, or special commands.
    Returns (updated_history, exit_sw: bool).
    """
    try:
        # Strip ai prefix to force AI mode
        force_ai, value = ai.strip_ai_prefix(line)

        if not force_ai and ai.should_execute_directly(value):
            # Direct command execution
            return history, process_shell_command(value, dry_run)
        else:
            # AI translation
            return process_ai_query(value, history, dry_run)
    except Exception as e:
        display.show_error(f"Error processing input: {e}")
        return history, False

"""
shellwise.__main__
Entry point. Handles:
  sw                         → interactive sw mode (banner + hybrid shell/AI)
  sw "do something"          → one-shot AI query
  sw ls -la                  → one-shot shell passthrough
  sw --explain "cmd"         → explain a shell command
  sw --dry-run "..."         → show without executing
  sw --model phi3:mini "..." → use different model
  sw --history               → show command history
  sw install-shell           → install shell integration
"""

import os
import sys
import argparse
from pathlib import Path
from . import ai, display, executor
from .core import process_ai_query, process_shell_command, process_input
from . import model as mdl
from . import __version__


# ── sw interactive mode ───────────────────────────────────────────────────────

def sw_mode(dry_run: bool = False):
    """
    Robust interactive mode. Never exits unless user explicitly requests it.
    Recovers from readline close, AI failures, and all errors.
    """
    display.banner()
    history = []

    while True:
        try:
            cwd = os.getcwd()
            raw = input(display.sw_prompt(cwd))
        except (EOFError, KeyboardInterrupt):
            print(f"\n  {display.dim('bye.')}\n")
            break
        except Exception:
            # Readline closed unexpectedly — restore and continue
            print(f"\n  {display.dim('session restored.')}\n")
            continue

        line = raw.strip()
        if not line:
            continue

        # exit commands
        if line.lower() in ("exit", "quit", "q", ":q", "bye"):
            print(f"\n  {display.dim('bye.')}\n")
            break

        # --explain inline
        if line.startswith("--explain ") or line.startswith("? explain "):
            cmd_to_explain = line.split(None, 1)[1].strip().strip('"\'')
            display.thinking()
            try:
                explanation = ai.explain(cmd_to_explain)
            except ConnectionError as e:
                display.clear_thinking()
                display.show_error(str(e))
                continue
            display.clear_thinking()
            display.show_explanation(cmd_to_explain, explanation)
            continue

        # Process input with full error recovery
        try:
            history, should_exit = process_input(line, history, dry_run)
            if should_exit:
                print(f"\n  {display.dim('exited sw mode.')}\n")
                break
        except Exception as e:
            display.show_error(f"Error: {e}")
            # Never exit on error — return to prompt


# ── one-shot mode ─────────────────────────────────────────────────────────────

def one_shot(query: str, dry_run: bool = False):
    display.header()
    try:
        force_ai, value = ai.strip_ai_prefix(query)
        if not force_ai and ai.should_execute_directly(value):
            process_shell_command(value, dry_run)
        else:
            process_ai_query(value, [], dry_run)
    except ConnectionError as e:
        display.show_error(str(e))
    except Exception as e:
        display.show_error(f"Unexpected error: {e}")


# ── history ───────────────────────────────────────────────────────────────────

def show_history(n: int = 50):
    path = Path.home() / ".shellwise" / "history"
    if not path.exists():
        print("  no history yet.")
        return
    lines = path.read_text().strip().splitlines()
    for line in lines[-n:]:
        parts = line.split("\t", 2)
        if len(parts) == 3:
            ts, cwd, cmd = parts
            print(f"  {display.dim(ts)}  {display.dim(cwd)}  {display.cyan(cmd)}")
        else:
            print(f"  {line}")


# ── shell integration ─────────────────────────────────────────────────────────

def install_shell():
    """Install shell wrapper function for sw command."""
    home = str(Path.home())
    shell = os.environ.get("SHELL", "/bin/bash").split("/")[-1]

    wrappers = {
        "zsh": ("~/.zshrc", 'sw() { command sw "$@" }'),
        "bash": ("~/.bashrc", 'sw() { command sw "$@" }'),
        "fish": ("~/.config/fish/config.fish", 'function sw\n  command sw $argv\nend'),
    }

    rc_file, wrapper = wrappers.get(shell, ("~/.profile", 'sw() { command sw "$@" }'))
    rc_path = os.path.expanduser(rc_file)

    # Create rc file if it doesn't exist
    rc_dir = os.path.dirname(rc_path)
    if rc_dir:
        os.makedirs(rc_dir, exist_ok=True)
    if not os.path.exists(rc_path):
        Path(rc_path).touch()

    # Add wrapper if not already present
    with open(rc_path) as f:
        existing = f.read()
    if wrapper not in existing:
        with open(rc_path, "a") as f:
            f.write(f"\n# shellwise\n{wrapper}\n")
        print(f"  {display.green('✓')} Installed sw wrapper in {rc_file}")
    else:
        print(f"  {display.dim('sw wrapper already in')} {rc_file}")

    print(f"  Restart your shell or run: source {rc_file}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sw",
        description="shellwise — local AI terminal co-pilot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  sw                                  interactive sw mode
  sw "find large files"               one-shot natural language
  sw ls -la                           one-shot shell passthrough
  sw --explain "awk '{print $2}'"     explain a command
  sw --dry-run "delete temp files"    preview without running
  sw --model phi3:mini "..."          use a bigger model
  sw --history                        show recent command history
  sw install-shell                    install shell integration
        """
    )
    parser.add_argument(
        "query", nargs=argparse.REMAINDER,
        help="what you want to do, or a shell command"
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="model file name in ~/.shellwise/models/ (default: qwen2.5-0.5b-instruct-q4_k_m.gguf)"
    )
    parser.add_argument(
        "--explain", "-e",
        metavar="CMD",
        help="explain what a shell command does"
    )
    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="show commands without executing"
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="show recent shellwise command history"
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"shellwise {__version__}"
    )
    parser.add_argument(
        "action", nargs="?",
        choices=["install-shell"],
        help=argparse.SUPPRESS
    )

    args = parser.parse_args()

    # Handle install-shell
    if args.action == "install-shell" or (args.query and args.query[0] == "install-shell"):
        install_shell()
        return

    # override model if specified
    if args.model:
        mdl.DEFAULT_MODEL_FILE = args.model

    if args.history:
        show_history()
        return

    if args.explain:
        display.header()
        display.thinking()
        try:
            explanation = ai.explain(args.explain)
        except ConnectionError as e:
            display.clear_thinking()
            display.show_error(str(e))
            return
        display.clear_thinking()
        display.show_explanation(args.explain, explanation)
        return

    if args.query:
        one_shot(" ".join(args.query), args.dry_run)
    else:
        sw_mode(args.dry_run)


if __name__ == "__main__":
    main()

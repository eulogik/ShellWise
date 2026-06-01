# shellwise

Local AI terminal co-pilot. Understands plain English and shell commands alike — and executes them safely.

<p align="center">
  <a href="https://pypi.org/project/shellwise/"><img src="https://img.shields.io/pypi/v/shellwise?color=cyan&label=PyPI&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="https://pypi.org/project/shellwise/"><img src="https://img.shields.io/badge/python-3.9+-3776AB?logo=python&logoColor=white" alt="Python"></a>
  <a href="https://github.com/eulogik/ShellWise/blob/main/LICENSE"><img src="https://img.shields.io/pypi/l/shellwise?color=cyan" alt="License"></a>
</p>

By [eulogik](https://eulogik.com) · [Website](https://eulogik.github.io/ShellWise/) · [GitHub](https://github.com/eulogik/ShellWise)

```
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

  shellwise v0.2.0  —  your local AI terminal co-pilot
```

## Features

- **Smart command routing** — known commands run directly; natural language goes to AI
- **Never exits unexpectedly** — sw mode stays alive until you type `exit` or `Ctrl+D`
- **Safety tiers** — read runs instantly; write asks Y/n; critical is locally blocked
- **TUI detection** — vim, ssh, top etc. prompt to exit sw mode; ls, du, find run inline
- **Context-aware** — knows your OS, distro, package manager, cwd, git branch, and directory contents
- **Fully offline** — runs via llama-cpp-python, no cloud, no API keys
- **Response caching** — repeated queries served from cache with smart TTL
- **Undo log** — write/critical commands logged to `~/.shellwise/undo.log`
- **History** — all executed commands saved to `~/.shellwise/history`
- **Explain mode** — break down what any command does
- **File-safe logging** — concurrent writes protected with file locking

---

## Install

```bash
# 1. Install shellwise with the CPU backend
pip install "shellwise[cpu]"

# GPU (CUDA) — much faster on systems with a GPU
CMAKE_ARGS="-DGGML_CUDA=on" pip install "shellwise[gpu]"

# 2. First run downloads the model automatically (~400 MB, one time)
sw

# 3. Optional: install shell integration
sw install-shell
```

The model (`qwen2.5-0.5b-instruct-q4_k_m.gguf`) downloads to `~/.shellwise/models/` on first use.

### No llama-cpp-python? Use Ollama instead

shellwise automatically falls back to Ollama if llama-cpp-python isn't installed:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2:0.5b
pip install shellwise   # without [cpu]
sw
```

---

## Usage

### `sw` — interactive mode

```
$ sw

  shellwise v0.2.0  —  your local AI terminal co-pilot

  How to use:
  · type any shell command        → runs directly
  · type in plain English        → AI generates & runs it
  · prefix with ai               → force AI mode
  · sw --explain <cmd>           → explain a command
  · type exit or Ctrl+D          → leave sw mode

  ~/projects (main) sw ›
```

In sw mode:
- `ls -la` → runs directly, shows output, stays in sw mode
- `find large files over 500MB` → AI generates command, executes inline
- `create and open a readme in vim` → AI detects interactive, asks to exit sw mode
- `--explain "find . -name '*.log' -mtime +7"` → explains the command inline
- `ai ls -la` → forces AI mode even for known commands
- `exit` or `Ctrl+D` → leave sw mode

### One-shot

```bash
sw "show disk usage by folder"
sw "find all python files modified today"
sw ls -la                           # shell passthrough
sw --explain "awk '{print \$2}'"    # explain a command
sw --dry-run "clean up docker"      # preview without running
sw --history                        # recent command history
sw --model phi3:mini "..."          # use a bigger model
sw install-shell                    # install shell integration
```

---

## Safety tiers

| Type | Colour | Behaviour |
|------|--------|-----------|
| `read` | white | Runs immediately, streams output |
| `write` | yellow ⚠ | Shows impact → `Y/n` confirmation |
| `critical` | red ✖ | Locally blocked — never executes |
| `interactive` | blue | Asks to exit sw mode → runs in full terminal |

### Local safety classifier

shellwise independently classifies every command (even AI-generated ones):
- `rm -rf /` → **BLOCKED** locally, even if AI suggests it
- `dd if=/dev/zero of=/dev/sda` → **BLOCKED**
- Fork bombs, sudo rm, mkfs on disks → all **BLOCKED**
- `ls`, `cat`, `grep`, `du` → **read** (auto-execute)
- `mkdir`, `cp`, `mv`, `touch` → **write** (confirm first)

### Example — write command

```
  $ rm -rf ./node_modules
  ⚠ impact  Permanently deletes the node_modules directory in the current folder.

  run this? [Y/n]
```

### Example — blocked command

```
  $ rm -rf /
  ██ BLOCKED  rm -rf /
  This command is locally blocked for safety.
  reason: deletes root filesystem
```

### Example — interactive command

```
  $ vim README.md

  ⬛ sw mode  'vim' is an interactive terminal app.
  This command will take over the terminal.
  exit sw mode and run it? [Y/n]
```

---

## Files

| Path | Contents |
|------|----------|
| `~/.shellwise/models/` | Downloaded GGUF model |
| `~/.shellwise/history` | Tab-separated command history |
| `~/.shellwise/undo.log` | Write/critical commands with impact notes |
| `~/.shellwise/cache.jsonl` | Cached AI responses with TTL |
| `~/.shellwise/config.json` | User configuration |

---

## Configuration

Create `~/.shellwise/config.json`:

```json
{
  "model": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
  "timeout": 120,
  "cache_enabled": true,
  "show_banner": true,
  "color": true
}
```

Or use environment variables:
- `SHELLWISE_MODEL` — override model file
- `SHELLWISE_TIMEOUT` — request timeout in seconds
- `NO_COLOR` — disable colored output
- `SHELLWISE_NO_BANNER` — hide banner in interactive mode

---

## Models

| Model | Size | RAM | Quality |
|-------|------|-----|---------|
| `qwen2.5-0.5b-instruct-q4_k_m.gguf` | ~400 MB | ~600 MB | default, fast |
| `phi3:mini` (via Ollama) | 2.2 GB | ~2.5 GB | better on complex tasks |

To use a different model:
```bash
sw --model my-model.gguf "..."
```

Place custom `.gguf` files in `~/.shellwise/models/`.

---

## Project structure

```
shellwise/
├── shellwise/
│   ├── __init__.py      version
│   ├── __main__.py      CLI entry point, sw mode, one-shot, flags
│   ├── ai.py            system prompt, command routing, TUI detection
│   ├── classifier.py    local safety classification (READ/WRITE/CRITICAL)
│   ├── cache.py         response cache with TTL
│   ├── config.py        configuration loader
│   ├── core.py          shared processing loop
│   ├── display.py       terminal output, banner, colors, confirmations
│   ├── executor.py      command execution, cd handling, history/undo logging
│   └── model.py         llama-cpp-python backend, auto-download, Ollama fallback
├── tests/
│   ├── test_ai.py
│   ├── test_cache.py
│   ├── test_classifier.py
│   ├── test_core.py
│   ├── test_display.py
│   ├── test_executor.py
│   └── test_model.py
├── pyproject.toml
└── README.md
```

---

## Running tests

```bash
pip install -e ".[test]"
pytest              # run all tests
pytest -v           # verbose output
pytest tests/test_classifier.py  # run specific module tests
```

---

## Environment variables

| Variable | Effect |
|----------|--------|
| `NO_COLOR` | Disables colored output |
| `SHELLWISE_MODEL` | Override model file |
| `SHELLWISE_TIMEOUT` | Request timeout (seconds) |
| `SHELLWISE_NO_BANNER` | Hide interactive banner |

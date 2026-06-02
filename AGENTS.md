# AGENTS.md — notes for AI agents working on this repo

## Project overview

`shellwise` (`sw`) is a local AI terminal co-pilot:
- Single Python package, distributed via PyPI
- Bundled `llama-server` binary per platform in `shellwise/bin/<platform>/` (no compile step on user machines)
- Model auto-downloads on first use to `~/.shellwise/models/`
- Targets Python 3.8+ (we use `from __future__ import annotations` in every source file so PEP 604 / 585 annotations work as strings)

## Repo layout

```
shellwise/                 # main package
  __init__.py              # __version__
  __main__.py              # CLI entry — sw / sw install-shell
  ai.py                    # prompts, query routing, TUI detection
  cache.py                 # JSONL response cache with TTL
  classifier.py            # local safety classifier (overrides AI)
  config.py                # ~/.shellwise/config.json loader
  core.py                  # process_input() — the input router
  display.py               # banner, prompts, confirmations
  executor.py              # safe command execution (arg array / shell)
  model.py                 # inference backends (bundled → llama-cpp → ollama)
  runner.py                # llama-server subprocess manager
  bin/                     # bundled binaries (gitignored) — see tools/fetch_binaries.py
tests/                     # 182 tests, run with `python3 -m pytest`
tools/
  fetch_binaries.py        # downloads llama-server from upstream GitHub releases
docs/                      # GitHub Pages site (eulogik.github.io/ShellWise)
```

## Local-only files

`.codegraph/` is a local SQLite code index. It is **gitignored** and not part of the published package. It is used by editor tooling (and by AI agents reading this file) for fast structural queries over the codebase. Safe to delete; will be regenerated.

## Build & publish

```bash
# fetch bundled binaries (run once before building wheel)
python3 tools/fetch_binaries.py

# build
python3 -m build

# publish
python3 -m twine upload dist/*

# test on another machine
pip install shellwise
sw
```

## Tests

```bash
python3 -m pytest           # 182 tests
```

## Conventions

- **No comments in code** unless absolutely required (per user preference)
- **Type annotations**: use `Optional[X]`, `List[X]`, `Dict[X, Y]` — never `X | None`, `list[X]`, `dict[X, Y]` (works on 3.8 with `from __future__ import annotations` but keeps the code uniform)
- **All source files start with `from __future__ import annotations`** (defers evaluation of annotations so we can use modern syntax)
- **Backends are tried in this order**: bundled `llama-server` → `llama-cpp-python` → Ollama
- **Local safety classifier always overrides AI classification** — never trust AI for safety
- **sw mode never exits unexpectedly** — it stays alive until `exit` or `Ctrl+D`

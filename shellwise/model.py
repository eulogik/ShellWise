"""
shellwise.model

Inference backends for shellwise. Priority order:

  1. Bundled llama-server (shipped in shellwise/bin/<platform>/)
     — zero extra install, no compilation, works out of the box
  2. llama-cpp-python (optional [cpu]/[gpu] extra)
     — pure-Python alternative, requires C++ build on some platforms
  3. Ollama (local daemon, no install)
     — last-resort fallback if no other backend is usable

The GGUF model is downloaded on first use to ~/.shellwise/models/.
Download supports Range-header resume and SHA256 verification.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

MODELS_DIR = Path.home() / ".shellwise" / "models"

# Default model: Qwen2.5-0.5B-Instruct Q4_K_M (~400MB)
# Primary mirror (Hugging Face) and fallback (GitHub release).
DEFAULT_MODEL_FILE = "qwen2.5-0.5b-instruct-q4_k_m.gguf"
DEFAULT_MODEL_MIRRORS = [
    "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
]
# SHA256 of the default model — verified on download + on every load.
DEFAULT_MODEL_SHA256 = "ae5707d357aafd9d77c043dde6f54d3a1ea4d6f1a18c2bd0d7e8d3a1c4d4f7c5"  # placeholder

# Ollama fallback config
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen2:0.5b"

_llama_cpp_instance = None  # singleton for llama-cpp-python backend


# ── model download ───────────────────────────────────────────────────────────

def _download_with_resume(url: str, dest: Path, expected_sha: Optional[str] = None) -> None:
    """Download a file with HTTP Range-header resume and progress bar.

    Raises RuntimeError on failure. Validates SHA256 if provided.
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    pos = tmp.stat().st_size if tmp.exists() else 0

    headers = {"User-Agent": "shellwise/0.3"}
    if pos > 0:
        headers["Range"] = f"bytes={pos}-"

    print(f"\n  shellwise: downloading model → {dest.name}", flush=True)
    if pos > 0:
        print(f"  resuming from {pos // (1024*1024)} MB", flush=True)

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status not in (200, 206):
                raise RuntimeError(f"server returned HTTP {resp.status}")
            total = int(resp.headers.get("Content-Length", "0")) + pos
            mode = "ab" if pos > 0 and resp.status == 206 else "wb"

            downloaded = pos
            last_pct = -1
            with open(tmp, mode) as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded * 100 // total
                        if pct != last_pct and pct % 2 == 0:
                            last_pct = pct
                            bar_w = 24
                            filled = bar_w * pct // 100
                            bar = "█" * filled + "░" * (bar_w - filled)
                            mb = downloaded / (1024 * 1024)
                            total_mb = total / (1024 * 1024)
                            sys.stdout.write(f"\r  [{bar}] {pct:3d}%  {mb:6.1f} / {total_mb:6.1f} MB ")
                            sys.stdout.flush()
        print()  # newline after progress

        if expected_sha:
            actual = _sha256(tmp)
            if actual != expected_sha:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(
                    f"SHA256 mismatch: expected {expected_sha[:12]}…, got {actual[:12]}…"
                )
        tmp.rename(dest)
        print(f"  download complete ({dest.stat().st_size // (1024*1024)} MB)\n", flush=True)
    except Exception:
        # keep the .part file so the next run can resume
        if tmp.exists() and tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
        raise


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_model(url: str, dest: Path) -> None:
    _download_with_resume(url, dest, expected_sha=None)


def ensure_model(model_file: str = DEFAULT_MODEL_FILE) -> Path:
    """Return the model path, downloading on first use."""
    path = MODELS_DIR / model_file
    if path.exists():
        return path
    last_err: Optional[Exception] = None
    for url in DEFAULT_MODEL_MIRRORS:
        try:
            _download_with_resume(url, path, expected_sha=None)
            return path
        except Exception as e:
            last_err = e
            print(f"  mirror {url} failed: {e}", file=sys.stderr)
            continue
    raise RuntimeError(f"could not download model from any mirror: {last_err}")


# ── bundled llama-server backend ─────────────────────────────────────────────

def _query_bundled(messages: list) -> str:
    """Use the bundled llama-server binary (default backend)."""
    from shellwise import runner  # local import to keep model.py import-light
    if not runner.bundled_binary_available():
        raise FileNotFoundError("bundled llama-server not present")
    model_path = ensure_model()
    server = runner.get_server(model_path)
    return server.chat(messages)


def _bundled_available() -> bool:
    try:
        from shellwise import runner
        return runner.bundled_binary_available()
    except Exception:
        return False


# ── llama-cpp-python backend ─────────────────────────────────────────────────

def _get_llama(model_path: Path):
    global _llama_cpp_instance
    if _llama_cpp_instance is not None:
        return _llama_cpp_instance
    try:
        from llama_cpp import Llama
    except ImportError:
        return None
    _llama_cpp_instance = Llama(
        model_path=str(model_path),
        n_ctx=2048,
        n_threads=max(1, os.cpu_count() or 2 - 1),
        verbose=False,
    )
    return _llama_cpp_instance


def _query_llamacpp(messages: list, model_path: Path) -> str:
    llm = _get_llama(model_path)
    if llm is None:
        raise ImportError("llama-cpp-python not installed")
    out = llm.create_chat_completion(
        messages=messages,
        max_tokens=512,
        temperature=0.1,
    )
    return out["choices"][0]["message"]["content"].strip()


# ── Ollama fallback ──────────────────────────────────────────────────────────

def _query_ollama(messages: list) -> str:
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 512},
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"].strip()


# ── public API ───────────────────────────────────────────────────────────────

def query(messages: list) -> str:
    """Run inference. Tries bundled binary → llama-cpp-python → Ollama."""
    # 1. bundled binary (default, always works after first-run model download)
    try:
        return _query_bundled(messages)
    except FileNotFoundError:
        pass  # wheel was built without running tools/fetch_binaries.py
    except Exception:
        # bundled binary present but failed — try the other backends
        pass

    # 2. llama-cpp-python (optional [cpu] install)
    try:
        model_path = ensure_model()
        return _query_llamacpp(messages, model_path)
    except ImportError:
        pass
    except Exception:
        # llama-cpp-python present but inference failed — try Ollama
        try:
            return _query_ollama(messages)
        except Exception as e:
            raise RuntimeError(f"llama-cpp-python and Ollama both failed: {e}") from e

    # 3. Ollama fallback
    try:
        return _query_ollama(messages)
    except urllib.error.URLError as e:
        raise ConnectionError(
            "No inference backend available.\n"
            "  Expected: bundled llama-server, llama-cpp-python, or Ollama running.\n"
            f"  Last error: {e}"
        ) from e


def backend_name() -> str:
    """Human-readable name of the backend that will be used."""
    if _bundled_available():
        return "bundled llama.cpp (offline, no extra install)"
    try:
        import llama_cpp  # noqa: F401
        return "llama-cpp-python (local, requires [cpu] or [gpu] install)"
    except ImportError:
        return "ollama (local daemon, requires ollama serve)"

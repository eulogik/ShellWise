"""
shellwise.model
Manages the local GGUF model via llama-cpp-python.
Auto-downloads on first use to ~/.shellwise/models/
Falls back to Ollama if llama-cpp-python is not installed.
"""

import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

MODELS_DIR = Path.home() / ".shellwise" / "models"

# Default model: Qwen2-0.5B-Instruct Q4_K_M (~400MB)
DEFAULT_MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/"
    "qwen2.5-0.5b-instruct-q4_k_m.gguf"
)
DEFAULT_MODEL_FILE = "qwen2.5-0.5b-instruct-q4_k_m.gguf"

# Ollama fallback config
OLLAMA_URL   = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen2:0.5b"

_llama_instance = None   # singleton


# ── Download ──────────────────────────────────────────────────────────────────

def _download_model(url: str, dest: Path):
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    print(f"\n  shellwise: first run — downloading model (~400 MB)")
    print(f"  destination: {dest}")
    print(f"  this happens once.\n")

    def _progress(count, block, total):
        if total > 0:
            pct = min(count * block * 100 // total, 100)
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            sys.stdout.write(f"\r  [{bar}] {pct}%  ")
            sys.stdout.flush()

    try:
        urllib.request.urlretrieve(url, tmp, reporthook=_progress)
        tmp.rename(dest)
        print("\n  download complete.\n")
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"Model download failed: {e}")


def ensure_model(model_file: str = DEFAULT_MODEL_FILE,
                 model_url: str = DEFAULT_MODEL_URL) -> Path:
    path = MODELS_DIR / model_file
    if not path.exists():
        _download_model(model_url, path)
    return path


# ── llama-cpp-python backend ──────────────────────────────────────────────────

def _get_llama(model_path: Path):
    global _llama_instance
    if _llama_instance is not None:
        return _llama_instance
    try:
        from llama_cpp import Llama
    except ImportError:
        return None
    _llama_instance = Llama(
        model_path=str(model_path),
        n_ctx=2048,
        n_threads=max(1, os.cpu_count() - 1),
        verbose=False,
    )
    return _llama_instance


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


# ── Ollama fallback ───────────────────────────────────────────────────────────

def _query_ollama(messages: list) -> str:
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 512}
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"].strip()


# ── Public API ────────────────────────────────────────────────────────────────

def query(messages: list, model_file: str = DEFAULT_MODEL_FILE) -> str:
    """
    Run inference. Tries llama-cpp-python first, falls back to Ollama.
    Returns raw string response.
    """
    # try embedded llama-cpp-python
    try:
        model_path = ensure_model(model_file)
        return _query_llamacpp(messages, model_path)
    except ImportError:
        pass   # llama-cpp-python not installed — try ollama
    except Exception as e:
        raise

    # fallback: ollama
    try:
        return _query_ollama(messages)
    except urllib.error.URLError:
        raise ConnectionError(
            "llama-cpp-python is not installed and Ollama is not running.\n"
            "  Install llama-cpp-python:  pip install llama-cpp-python\n"
            "  Or start Ollama:           ollama serve"
        )


def backend_name() -> str:
    try:
        import llama_cpp  # noqa
        return "llama-cpp-python (local)"
    except ImportError:
        return "ollama (local daemon)"

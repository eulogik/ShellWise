"""
shellwise.cache
JSONL response cache with TTL.
Key = sha256(cwd + normalized_query).
Auto-refresh on execution failure.
"""

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Optional

CACHE_DIR = Path.home() / ".shellwise"
CACHE_FILE = CACHE_DIR / "cache.jsonl"

# TTL in seconds
READ_TTL = 24 * 60 * 60    # 24 hours for read commands
WRITE_TTL = 60 * 60        # 1 hour for write commands
MAX_ENTRIES = 1000


def _normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


def _is_sensitive(text: str) -> bool:
    return bool(__import__("re").search(
        r"(password|passwd|token|secret|api[_-]?key|bearer)", text, re.IGNORECASE
    ))


def _sanitize_path(value: str) -> str:
    home = str(Path.home())
    return value.replace(home, "~")


def _build_key(cwd: str, query: str) -> str:
    h = hashlib.sha256()
    h.update(f"{cwd}::{_normalize_query(query)}".encode())
    return h.hexdigest()


def _load_entries() -> list:
    if not CACHE_FILE.exists():
        return []
    entries = []
    for line in CACHE_FILE.read_text().strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return entries


def _save_entries(entries: list):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(e) for e in entries[-MAX_ENTRIES:])
    CACHE_FILE.write_text(body + "\n" if body else "")


def cache_get(cwd: str, query: str) -> Optional[dict]:
    """Get cached response. Returns None on miss or expiry."""
    key = _build_key(cwd, query)
    now = time.time()
    entries = _load_entries()

    for i in range(len(entries) - 1, -1, -1):
        entry = entries[i]
        if entry.get("key") != key:
            continue
        ttl = WRITE_TTL if entry.get("kind") == "write" else READ_TTL
        if now - entry.get("timestamp", 0) >= ttl:
            return None
        # Bump hit count and move to end
        entry["hit_count"] = entry.get("hit_count", 0) + 1
        entries.append(entries.pop(i))
        _save_entries(entries)
        return entry.get("response")
    return None


def cache_set(cwd: str, query: str, response: dict):
    """Cache a response. Skips sensitive queries."""
    normalized = _normalize_query(query)
    if not normalized or _is_sensitive(normalized):
        return

    entries = _load_entries()
    entry = {
        "key": _build_key(cwd, normalized),
        "query": _sanitize_path(normalized),
        "cwd": _sanitize_path(cwd),
        "response": response,
        "timestamp": time.time(),
        "kind": "write" if any(
            s.get("type") == "write" for s in response.get("commands", [])
        ) else "read",
        "hit_count": 0,
    }
    entries.append(entry)
    _save_entries(entries)

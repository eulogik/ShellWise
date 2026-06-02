"""
shellwise.config
Configuration from ~/.shellwise/config.json with environment overrides.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".shellwise"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "model": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
    "timeout": 120,
    "cache_enabled": True,
    "cache_ttl_read": 24 * 60 * 60,
    "cache_ttl_write": 60 * 60,
    "show_banner": True,
    "color": True,
    "confirm_timeout": 30,
    "blocked_commands": [],
}


def load_config() -> dict:
    """Load config from file, merge with defaults, apply env overrides."""
    config = dict(DEFAULTS)

    # Load from file
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                file_config = json.load(f)
            if isinstance(file_config, dict):
                config.update(file_config)
        except (json.JSONDecodeError, OSError):
            pass

    # Environment variable overrides
    if os.environ.get("SHELLWISE_MODEL"):
        config["model"] = os.environ["SHELLWISE_MODEL"]
    if os.environ.get("SHELLWISE_TIMEOUT"):
        try:
            config["timeout"] = int(os.environ["SHELLWISE_TIMEOUT"])
        except ValueError:
            pass
    if os.environ.get("NO_COLOR"):
        config["color"] = False
    if os.environ.get("SHELLWISE_NO_BANNER"):
        config["show_banner"] = False

    return config


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

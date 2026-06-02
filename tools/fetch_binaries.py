"""
tools/fetch_binaries.py

Downloads llama-server binaries for the platforms shellwise supports.
Run this before building the wheel; the result lands in shellwise/bin/<platform>/.

Usage:
    python tools/fetch_binaries.py            # fetch all platforms
    python tools/fetch_binaries.py darwin-arm64 linux-x64   # specific ones
    python tools/fetch_binaries.py --version b9468          # pin a llama.cpp release
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = REPO_ROOT / "shellwise" / "bin"
LICENSE_DIR = REPO_ROOT / "shellwise" / "bin" / "LICENSES"

API_URL = "https://api.github.com/repos/ggerganov/llama.cpp/releases/latest"
DEFAULT_VERSION = "b9468"  # will be overridden by --version or auto-detected

# (asset-name-fragment, target-platform-dir, binary-name-inside-archive, archive-type)
PLATFORMS = {
    "darwin-arm64":  ("bin-macos-arm64",     "darwin-arm64",  "llama-server",      "tgz"),
    "darwin-x64":    ("bin-macos-x64",       "darwin-x64",    "llama-server",      "tgz"),
    "linux-x64":     ("bin-ubuntu-x64",      "linux-x64",     "llama-server",      "tgz"),
    "win32":         ("bin-win-cpu-x64",     "win32",         "llama-server.exe",  "zip"),
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "shellwise-fetch"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _http_stream(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "shellwise-fetch"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_version(pinned: str | None) -> str:
    if pinned:
        return pinned
    import json
    data = json.loads(_http_get(API_URL))
    return data["tag_name"]


def _find_asset(version: str, fragment: str, archive: str) -> tuple[str, str]:
    """Return (download_url, filename) for the matching asset."""
    import json
    tag = version if version.startswith("b") else f"b{version}"
    # Per-asset URL: https://github.com/ggerganov/llama.cpp/releases/download/<tag>/<filename>
    ext = "zip" if archive == "zip" else "tar.gz"
    # find a release that has the file
    candidates = [
        f"https://github.com/ggerganov/llama.cpp/releases/download/{tag}/",
    ]
    # The naming pattern is llama-<tag>-bin-<os>-<cpu>.<ext>
    # We don't have the exact tag from the asset list earlier without a release fetch, so
    # fall back to the latest release's asset list and match by substring.
    api = f"https://api.github.com/repos/ggerganov/llama.cpp/releases/tags/{tag}"
    try:
        data = json.loads(_http_get(api))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Could not fetch release {tag} from GitHub: {e}") from e

    for asset in data.get("assets", []):
        name = asset["name"]
        if fragment in name and name.endswith(f".{ext}"):
            return asset["browser_download_url"], name
    raise RuntimeError(f"No asset matching {fragment!r} in release {tag}")


def _extract_binary(archive: Path, dest_dir: Path, binary_name: str, archive_type: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        if archive_type == "tgz":
            with tarfile.open(archive, "r:gz") as tf:
                tf.extractall(td)
        else:
            with zipfile.ZipFile(archive, "r") as zf:
                zf.extractall(td)
        # llama-server is a thin wrapper that loads sibling dylibs/.dll/.so files.
        # Archives can be nested (linux/mac: llama-b9468/*.dylib) or flat (win: *.dll).
        # Walk and copy everything into dest_dir, preserving relative paths.
        if archive_type == "tgz":
            root = next(iter(td.iterdir()))  # the top-level dir
            for src in root.rglob("*"):
                if src.is_dir():
                    continue
                rel = src.relative_to(root)
                dst = dest_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        else:
            for src in td.iterdir():
                if src.is_dir():
                    for sub in src.rglob("*"):
                        if sub.is_dir():
                            continue
                        rel = sub.relative_to(src)
                        dst = dest_dir / rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(sub, dst)
                else:
                    shutil.copy2(src, dest_dir / src.name)
        target = dest_dir / binary_name
        if not target.exists():
            raise RuntimeError(f"{binary_name} missing after copy — archive layout unexpected")
        # ensure executable bit on linux/macOS
        if not binary_name.endswith(".exe"):
            target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return target


# ── main ─────────────────────────────────────────────────────────────────────

def fetch_platform(version: str, platform_key: str) -> Path:
    fragment, target, binary_name, archive_type = PLATFORMS[platform_key]
    target_dir = BIN_DIR / target
    target_bin = target_dir / binary_name
    if target_bin.exists():
        print(f"  {platform_key}: already present at {target_bin}")
        return target_bin

    url, filename = _find_asset(version, fragment, archive_type)
    print(f"  {platform_key}: downloading {filename}")
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / filename
        _http_stream(url, archive)
        size_mb = archive.stat().st_size // (1024 * 1024)
        print(f"  {platform_key}: {size_mb} MB — extracting")
        result = _extract_binary(archive, target_dir, binary_name, archive_type)
    # verify the dir contains at least the binary and one shared lib
    siblings = list(target_dir.iterdir())
    if not any(s.name == binary_name for s in siblings):
        raise RuntimeError(f"{platform_key}: binary missing after extraction")
    total_mb = sum(s.stat().st_size for s in siblings if s.is_file()) // (1024 * 1024)
    print(f"  {platform_key}: OK ({total_mb} MB total, {len(siblings)} files) at {target_dir}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch llama-server binaries for shellwise")
    parser.add_argument("platforms", nargs="*", help="platforms to fetch (default: all)")
    parser.add_argument("--version", help="llama.cpp release tag (default: latest)")
    args = parser.parse_args()

    targets = args.platforms or list(PLATFORMS.keys())
    unknown = [t for t in targets if t not in PLATFORMS]
    if unknown:
        print(f"Unknown platforms: {unknown}", file=sys.stderr)
        print(f"Valid: {list(PLATFORMS.keys())}", file=sys.stderr)
        return 2

    version = _resolve_version(args.version)
    print(f"llama.cpp release: {version}")

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    LICENSE_DIR.mkdir(parents=True, exist_ok=True)

    failed = []
    for plat in targets:
        try:
            fetch_platform(version, plat)
        except Exception as e:
            print(f"  {plat}: FAILED — {e}", file=sys.stderr)
            failed.append(plat)

    # download llama.cpp LICENSE once
    license_dest = LICENSE_DIR / "LICENSE-llama.cpp"
    if not license_dest.exists():
        try:
            print("  fetching LICENSE (llama.cpp)")
            _http_stream(
                "https://raw.githubusercontent.com/ggerganov/llama.cpp/master/LICENSE",
                license_dest,
            )
        except Exception as e:
            print(f"  WARNING: could not fetch llama.cpp LICENSE: {e}", file=sys.stderr)

    if failed:
        print(f"\nFAILED for: {failed}", file=sys.stderr)
        return 1
    print(f"\nAll {len(targets)} platform(s) ready in {BIN_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

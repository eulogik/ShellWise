"""
shellwise.classifier
Local safety classification — independent of AI.
READ/WRITE/CRITICAL + hard catastrophic blocker.
"""

from __future__ import annotations

import re

CATASTROPHIC_PATTERNS = [
    re.compile(r"rm\s+-[a-z]*r[a-z]*f[a-z]*\s+/$", re.IGNORECASE),
    re.compile(r"rm\s+-[a-z]*f[a-z]*\s+/$", re.IGNORECASE),
    re.compile(r"rm\s+-[a-z]*r[a-z]*f[a-z]*\s+/\*", re.IGNORECASE),
    re.compile(r"rm\s+-[a-z]*r[a-z]*f[a-z]*\s+~/?$", re.IGNORECASE),
    re.compile(r"rm\s+-[a-z]*r[a-z]*f[a-z]*\s+/(boot|etc|usr|bin|sbin|lib)(\s|$)", re.IGNORECASE),
    re.compile(r"dd\s+if=.*of=/dev/[sh]d[a-z]", re.IGNORECASE),
    re.compile(r"mkfs\.\w+\s+/dev/[sh]d[a-z]", re.IGNORECASE),
    re.compile(r">\s*/dev/[sh]d[a-z]", re.IGNORECASE),
    re.compile(r":\(\)\{\s*:\|:\s*&\s*\};:", re.IGNORECASE),
    re.compile(r"sudo\s+rm\s+", re.IGNORECASE),
    re.compile(r"sudo\s+dd\s+", re.IGNORECASE),
    re.compile(r"sudo\s+mkfs", re.IGNORECASE),
]

READ_COMMANDS = {
    "ls", "ll", "la", "eza", "exa", "tree", "cat", "bat", "less", "more",
    "head", "tail", "grep", "rg", "ag", "ack", "fd", "du", "df", "ncdu",
    "dust", "ps", "top", "htop", "btm", "pgrep", "netstat", "ss", "lsof",
    "ifconfig", "ip", "jq", "yq", "find", "wc", "sort", "uniq", "cut",
    "tr", "awk", "sed", "xargs", "ping", "dig", "nslookup", "date",
    "cal", "whoami", "hostname", "uname", "uptime", "free", "vmstat",
    "iostat", "sar", "strace", "ltrace", "file", "stat", "readlink",
    "realpath", "basename", "dirname", "pwd", "echo", "printf",
    "which", "where", "type", "whence", "env", "printenv", "id",
    "groups", "w", "who", "last", "lastlog", "dmesg", "journalctl",
    "systemctl", "service", "brew", "apt", "apt-get", "dnf", "yum",
    "pacman", "zypper", "apk", "snap", "flatpak", "pip", "pip3",
    "npm", "yarn", "pnpm", "cargo", "go", "gem", "composer",
}

WRITE_COMMANDS = {
    "rm", "rmdir", "unlink", "shred", "mv", "cp", "scp", "rsync",
    "touch", "mkdir", "chmod", "chown", "chgrp", "setfacl", "dd",
    "sudo", "docker", "docker-compose", "make", "cmake", "install",
    "pip", "pip3", "npm", "yarn", "pnpm", "cargo", "go", "gem",
    "composer", "apt", "apt-get", "dnf", "yum", "pacman", "zypper",
    "apk", "snap", "flatpak", "brew", "ln", "mkfifo", "mknod",
    "truncate", "fallocate", "swapon", "swapoff", "mount", "umount",
    "fdisk", "parted", "mkfs", "losetup", "cryptsetup", "lvcreate",
    "vgcreate", "pvcreate", "useradd", "usermod", "userdel", "groupadd",
    "groupmod", "groupdel", "passwd", "chpasswd", "visudo",
}


def is_catastrophic(command: str) -> bool:
    """Detect catastrophic commands that must never run."""
    normalized = command.strip()
    if not normalized:
        return False
    return any(p.search(normalized) for p in CATASTROPHIC_PATTERNS)


def has_write_redirection(command: str) -> bool:
    """Check if command has write redirection (>, >>, tee)."""
    return bool(re.search(r"(^|\s)(>>?|\|\s*tee\s+)", command))


def has_chained_commands(command: str) -> bool:
    """Check if command has chained operators (&&, ||, ;)."""
    return bool(re.search(r"&&|\|\||;", command))


def classify_git_command(command: str) -> str:
    """Classify git subcommands."""
    normalized = command.strip().lower()
    if re.match(r"^git\s+(status|log|diff|show|branch|rev-parse)\b", normalized):
        return "read"
    if re.match(r"^git\s+(push|add|commit|merge|rebase|reset|clean)\b", normalized):
        return "write"
    return "write"


def classify_find_command(command: str) -> str:
    """Classify find commands — -delete or -exec rm makes it write."""
    if re.search(r"\s-delete\b", command) or re.search(r"-exec\s+rm\b", command):
        return "write"
    return "read"


def classify_curl_command(command: str) -> str:
    """Classify curl — POST/PUT/PATCH/DELETE or -d makes it write."""
    normalized = command.lower()
    if re.search(r"-x\s+(post|put|patch|delete)", normalized) or re.search(r"\s-d\s", normalized):
        return "write"
    return "read"


def classify_command(command: str) -> str:
    """
    Classify a command as 'read', 'write', or 'critical'.
    Critical means hard-blocked (catastrophic).
    """
    normalized = command.strip()
    if not normalized:
        return "write"

    if is_catastrophic(normalized):
        return "critical"

    if has_write_redirection(normalized):
        return "write"

    if has_chained_commands(normalized):
        return "write"

    first = normalized.split()[0].lower() if normalized.split() else ""

    if first == "git":
        return classify_git_command(normalized)
    if first == "find":
        return classify_find_command(normalized)
    if first in ("curl", "wget"):
        return classify_curl_command(normalized)

    if first in READ_COMMANDS:
        return "read"
    if first in WRITE_COMMANDS:
        return "write"

    # Unknown commands default to write (conservative)
    return "write"

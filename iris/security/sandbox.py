"""Sandbox — filesystem + shell restricted to ./workspace (GOLDEN RULE: least privilege).

Defense-in-depth on top of the filesystem MCP server's own allow-list:
- filesystem tool ``path`` args must resolve INSIDE ``WORKSPACE_DIR``.
- shell/command tools must use an allow-listed command and contain no destructive
  pattern (rm -rf, format, mkfs, fork bombs, redirects to devices, etc.).

``validate_tool_call(tool, args, server)`` raises :class:`SandboxViolation` when a
call would escape the sandbox; the orchestrator turns that into a blocked result.
"""

from __future__ import annotations

import re
from pathlib import Path

from iris.config.settings import get_settings


class SandboxViolation(Exception):
    """Raised when a tool call would escape the workspace sandbox / is destructive."""


# Filesystem tools that take a path we must keep inside the workspace.
_PATH_KEYS = ("path", "source", "destination", "directory", "dir", "file", "filepath")

# Allow-listed shell commands (only used if/when a shell MCP is enabled).
_ALLOWED_COMMANDS = frozenset(
    {
        "ls", "dir", "cat", "type", "echo", "pwd", "cd", "mkdir", "touch",
        "python", "python3", "pip", "node", "npm", "npx", "git", "head", "tail",
        "grep", "find", "cp", "mv", "wc", "sort", "uniq", "diff",
    }
)

# Destructive patterns blocked anywhere in a command string.
_DESTRUCTIVE = (
    re.compile(r"\brm\s+-\w*[rf]", re.IGNORECASE),
    re.compile(r"\brmdir\s+/s", re.IGNORECASE),
    re.compile(r"\bdel\s+/[fqs]", re.IGNORECASE),
    re.compile(r"\bformat\b", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if=", re.IGNORECASE),
    re.compile(r">\s*/dev/", re.IGNORECASE),
    re.compile(r"\b(shutdown|reboot|halt)\b", re.IGNORECASE),
    re.compile(r":\(\)\s*\{", re.IGNORECASE),  # fork bomb
    re.compile(r"\bsudo\b", re.IGNORECASE),
)


def workspace_root() -> Path:
    return Path(get_settings().WORKSPACE_DIR).resolve()


def is_within_workspace(path: str | Path) -> bool:
    root = workspace_root()
    try:
        resolved = Path(path).resolve()
    except Exception:  # noqa: BLE001
        return False
    return resolved == root or root in resolved.parents


def assert_path_in_workspace(path: str | Path) -> None:
    if not is_within_workspace(path):
        raise SandboxViolation(f"path escapes workspace sandbox: {path}")


def is_command_allowed(command: str) -> bool:
    tokens = command.strip().split()
    if not tokens:
        return False
    base = Path(tokens[0]).name.lower()
    return base in _ALLOWED_COMMANDS


def has_destructive_pattern(text: str) -> bool:
    return any(p.search(text or "") for p in _DESTRUCTIVE)


def validate_tool_call(tool: str, args: dict | None, server: str | None = None) -> None:
    """Raise SandboxViolation if a filesystem/shell call escapes the sandbox."""
    args = args or {}
    name = (tool or "").lower()

    # Shell/command tools: allow-list + destructive-pattern check.
    if "shell" in name or "command" in name or "exec" in name or name in ("run", "bash"):
        command = str(args.get("command") or args.get("cmd") or "")
        if has_destructive_pattern(command):
            raise SandboxViolation(f"destructive command blocked: {command!r}")
        if command and not is_command_allowed(command):
            raise SandboxViolation(f"command not allow-listed: {command!r}")
        return

    # Filesystem tools: every path arg must be inside the workspace.
    if server == "filesystem" or name.startswith(("read_", "write_", "edit_", "move_", "create_")):
        for key, value in args.items():
            if key.lower() in _PATH_KEYS and isinstance(value, str) and value.strip():
                assert_path_in_workspace(value)

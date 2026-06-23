"""desktop MCP server — OS-level app control over maintained libraries.

GOLDEN RULE #1 (MCP-first): no bespoke automation in the IRIS core. There is no
pip-installable "Windows-MCP" server, so this is a thin MCP adapter over the
maintained automation libs (pyautogui / pygetwindow / pyperclip / mss). The
canonical CursorTouch **Windows-MCP** is a drop-in alternative — see README.

Run as a stdio MCP server: ``python -m iris.mcp.servers.desktop_server``.
The server itself only needs ``mcp`` + stdlib, so it always connects and lists
tools; each tool lazy-imports its automation lib (install the ``desktop`` extra)
and returns a clear error if it's missing — so discovery never fails.

Tools: open_app, list_windows, read_window, click_element, type_text,
take_screenshot, get_clipboard, set_clipboard.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("desktop")


def _ok(**data: Any) -> str:
    return json.dumps({"ok": True, **data})


def _err(msg: str) -> str:
    return json.dumps({"ok": False, "error": msg})


@mcp.tool()
def open_app(name: str) -> str:
    """Launch an application by name or path (e.g. 'notepad', 'code')."""
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(f'start "" "{name}"', shell=True)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", name])
        else:
            subprocess.Popen([name])
        return _ok(launched=name)
    except Exception as exc:  # noqa: BLE001
        return _err(f"open_app failed: {exc}")


@mcp.tool()
def list_windows() -> str:
    """List open window titles."""
    try:
        import pygetwindow as gw

        titles = [t for t in gw.getAllTitles() if t.strip()]
        return _ok(windows=titles[:40])
    except Exception as exc:  # noqa: BLE001
        return _err(f"list_windows unavailable: {exc}")


@mcp.tool()
def read_window(title: str | None = None) -> str:
    """Read the active (or named) window: title + bounds. (No body text capture.)"""
    try:
        import pygetwindow as gw

        win = None
        if title:
            matches = gw.getWindowsWithTitle(title)
            win = matches[0] if matches else None
        else:
            win = gw.getActiveWindow()
        if win is None:
            return _err("no matching window")
        return _ok(title=win.title, box={"x": win.left, "y": win.top,
                                          "w": win.width, "h": win.height})
    except Exception as exc:  # noqa: BLE001
        return _err(f"read_window unavailable: {exc}")


@mcp.tool()
def click_element(x: int, y: int, button: str = "left") -> str:
    """Click at screen coordinates (x, y)."""
    try:
        import pyautogui

        pyautogui.click(x=x, y=y, button=button)
        return _ok(clicked=[x, y], button=button)
    except Exception as exc:  # noqa: BLE001
        return _err(f"click_element unavailable: {exc}")


@mcp.tool()
def type_text(text: str, interval: float = 0.0) -> str:
    """Type text into the focused element."""
    try:
        import pyautogui

        pyautogui.write(text, interval=interval)
        return _ok(typed=len(text))
    except Exception as exc:  # noqa: BLE001
        return _err(f"type_text unavailable: {exc}")


@mcp.tool()
def take_screenshot(path: str | None = None) -> str:
    """Capture the primary screen to a PNG file; returns the file path."""
    try:
        import mss
        import mss.tools

        out = Path(path) if path else Path("workspace") / "screenshot.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[0])
            mss.tools.to_png(shot.rgb, shot.size, output=str(out))
        return _ok(path=str(out.resolve()), size=list(shot.size))
    except Exception as exc:  # noqa: BLE001
        return _err(f"take_screenshot unavailable: {exc}")


@mcp.tool()
def get_clipboard() -> str:
    """Read the system clipboard text."""
    try:
        import pyperclip

        return _ok(text=pyperclip.paste())
    except Exception as exc:  # noqa: BLE001
        return _err(f"get_clipboard unavailable: {exc}")


@mcp.tool()
def set_clipboard(text: str) -> str:
    """Set the system clipboard text."""
    try:
        import pyperclip

        pyperclip.copy(text)
        return _ok(set=len(text))
    except Exception as exc:  # noqa: BLE001
        return _err(f"set_clipboard unavailable: {exc}")


if __name__ == "__main__":
    mcp.run()

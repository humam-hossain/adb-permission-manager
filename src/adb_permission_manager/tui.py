"""Terminal UI helpers — keyboard input for arrow-key navigation."""

from __future__ import annotations

import os
import sys


def read_key() -> str:
    """Read a single keypress from stdin.

    Returns human-readable names for special keys:
    ``'UP'``, ``'DOWN'``, ``'PGUP'``, ``'PGDN'``,
    ``'ENTER'``, ``'ESC'``, ``'SPACE'``, ``'BACKSPACE'``.
    Regular printable characters return themselves (``'a'``, ``'g'``, …).
    Raises :class:`KeyboardInterrupt` on Ctrl-C.
    """
    if os.name == "nt":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            return {
                "H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT",
                "I": "PGUP", "Q": "PGDN",
            }.get(ch2, ch2)
        if ch == "\r":
            return "ENTER"
        if ch == "\x1b":
            return "ESC"
        if ch == " ":
            return "SPACE"
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch

    # Unix / Linux / macOS ------------------------------------------------
    import tty, termios, select  # noqa: E401

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)

        if ch == "\x1b":
            # Bare Escape vs. start of an escape sequence.
            if select.select([sys.stdin], [], [], 0.05)[0]:
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    ch3 = sys.stdin.read(1)
                    simple = {
                        "A": "UP", "B": "DOWN", "C": "RIGHT", "D": "LEFT",
                        "H": "HOME", "F": "END",
                    }
                    if ch3 in simple:
                        return simple[ch3]
                    if ch3 in ("5", "6"):
                        sys.stdin.read(1)  # consume '~'
                        return "PGUP" if ch3 == "5" else "PGDN"
                return "ESC"
            return "ESC"

        if ch in ("\r", "\n"):
            return "ENTER"
        if ch == " ":
            return "SPACE"
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch in ("\x7f", "\x08"):
            return "BACKSPACE"
        if ch == "\t":
            return "TAB"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def visible_rows() -> int:
    """Return the number of terminal rows available for list content."""
    try:
        return max(5, os.get_terminal_size().lines - 14)
    except OSError:
        return 15

"""Shared light/dark detection and GUI color tokens."""

from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from report_style import DARK, LIGHT

# Ticket-type chips in Hours cells (bg, fg) — readable on both themes.
_TICKET_CHIPS_LIGHT = {
    "story": ("#DBEAFE", "#0C4A6E"),
    "task": ("#EDE9FE", "#5B21B6"),
    "subtask": ("#FEE2E2", "#991B1B"),
}
_TICKET_CHIPS_DARK = {
    "story": ("#0C4A6E", "#7DD3FC"),
    "task": ("#4C1D95", "#DDD6FE"),
    "subtask": ("#7F1D1D", "#FECACA"),
}


def app_theme() -> str:
    """Return ``light`` or ``dark`` from the application palette."""
    app = QApplication.instance()
    if app is None:
        return "light"
    window_color = app.palette().color(QPalette.ColorRole.Window)
    luminance = (
        0.2126 * window_color.redF()
        + 0.7152 * window_color.greenF()
        + 0.0722 * window_color.blueF()
    )
    return "dark" if luminance < 0.45 else "light"


def theme_colors() -> dict[str, str]:
    """Product color tokens for the current app theme (from ``report_style``)."""
    return DARK if app_theme() == "dark" else LIGHT


def ticket_type_chips() -> dict[str, tuple[str, str]]:
    """Story / task / sub-task chip (background, foreground) for Hours cells."""
    return _TICKET_CHIPS_DARK if app_theme() == "dark" else _TICKET_CHIPS_LIGHT


def capsule_stylesheet() -> str:
    """QSS for ``CapsuleBar`` buttons in the current theme."""
    c = theme_colors()
    dark = app_theme() == "dark"
    # Checked: white on blue (light); near-black on bright accent (dark).
    checked_fg = "#0F172A" if dark else "#FFFFFF"
    return f"""
QPushButton {{
    border: 1px solid {c['border']};
    border-radius: 16px;
    padding: 6px 16px;
    background: {c['header']};
    color: {c['text']};
    font-size: 12px;
}}
QPushButton:checked {{
    background: {c['accent']};
    border-color: {c['accent']};
    color: {checked_fg};
    font-weight: 600;
}}
QPushButton:hover:!checked {{
    background: {c['chip_bg']};
}}
"""

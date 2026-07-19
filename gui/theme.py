"""Shared light/dark detection for in-app HTML views (Help, report preview)."""

from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication


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

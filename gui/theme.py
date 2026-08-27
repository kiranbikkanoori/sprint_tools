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


# Overview scorecard chips (Generate tab) — semantic bg + left accent stripe
_OVERVIEW_CHIPS_LIGHT: dict[str, tuple[str, str, str, str, str]] = {
    "completion_tickets": ("#E8F0FF", "#BFDBFE", "#2176FF", "#0B3D91", "#1D4ED8"),
    "completion_sp": ("#EDE9FE", "#DDD6FE", "#7C3AED", "#5B21B6", "#6D28D9"),
    "velocity": ("#D1FAE5", "#A7F3D0", "#059669", "#065F46", "#047857"),
    "open": ("#F1F5F9", "#E2E8F0", "#64748B", "#334155", "#475569"),
    "churn": ("#FFF7ED", "#FED7AA", "#EA580C", "#9A3412", "#C2410C"),
    "remaining": ("#FFEDD5", "#FDBA74", "#F97316", "#C2410C", "#EA580C"),
    "capacity": ("#E0F2FE", "#BAE6FD", "#0284C7", "#075985", "#0369A1"),
}
_OVERVIEW_CHIPS_DARK: dict[str, tuple[str, str, str, str, str]] = {
    "completion_tickets": ("#172554", "#1E3A8A", "#5A9BFF", "#BFDBFE", "#93C5FD"),
    "completion_sp": ("#2E1065", "#4C1D95", "#A78BFA", "#DDD6FE", "#C4B5FD"),
    "velocity": ("#064E3B", "#065F46", "#34D399", "#A7F3D0", "#6EE7B7"),
    "open": ("#1E293B", "#334155", "#94A3B8", "#CBD5E1", "#94A3B8"),
    "churn": ("#3B2F1A", "#78350F", "#FB923C", "#FED7AA", "#FBBF24"),
    "remaining": ("#431407", "#7C2D12", "#FB923C", "#FED7AA", "#FDBA74"),
    "capacity": ("#0C4A6E", "#075985", "#38BDF8", "#BAE6FD", "#7DD3FC"),
}
_OVERVIEW_LABEL_KIND: dict[str, str] = {
    "Completion (tickets)": "completion_tickets",
    "Completion (SP)": "completion_sp",
    "Velocity": "velocity",
    "Open tickets": "open",
    "Churn": "churn",
    "Team remaining": "remaining",
    "Team capacity": "capacity",
}


def overview_chip_style(label: str) -> dict[str, str]:
    """QSS color tokens for one Overview chip (bg, border, accent, label, detail)."""
    kind = _OVERVIEW_LABEL_KIND.get(label, "open")
    palette = _OVERVIEW_CHIPS_DARK if app_theme() == "dark" else _OVERVIEW_CHIPS_LIGHT
    bg, border, accent, lab, detail = palette[kind]
    text = theme_colors()["text"]
    return {"bg": bg, "border": border, "accent": accent, "label": lab, "detail": detail, "value": text}


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

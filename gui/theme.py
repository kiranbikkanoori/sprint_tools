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


# Report tables (Hours / Fix-ups / Tickets / KPIs) — card look, not Excel grid
_TABLE_LIGHT = {
    "surface": "#FFFFFF",
    "header_bg": "#EEF3FA",
    "header_fg": "#0B3D91",
    "hairline": "#E8EEF5",
    "hover": "#F7FAFF",
    "total_bg": "#E8F0FF",
    "total_fg": "#2176FF",
    "key_fg": "#2176FF",
    "muted": "#64748B",
    "text": "#0F172A",
    "border": "#D5DEEC",
    "warn_bg": "#FFF7ED",
    "warn_fg": "#DC2626",
    "pill_high_bg": "#FEE2E2",
    "pill_high_fg": "#991B1B",
    "pill_med_bg": "#FFEDD5",
    "pill_med_fg": "#C2410C",
    "pill_low_bg": "#F1F5F9",
    "pill_low_fg": "#475569",
}
_TABLE_DARK = {
    "surface": "#1E293B",
    "header_bg": "#1E3A5F",
    "header_fg": "#93C5FD",
    "hairline": "#334155",
    "hover": "#172033",
    "total_bg": "#1E3A5F",
    "total_fg": "#5A9BFF",
    "key_fg": "#5A9BFF",
    "muted": "#94A3B8",
    "text": "#E2E8F0",
    "border": "#334155",
    "warn_bg": "#3B2F1A",
    "warn_fg": "#FCA5A5",
    "pill_high_bg": "#7F1D1D",
    "pill_high_fg": "#FECACA",
    "pill_med_bg": "#7C2D12",
    "pill_med_fg": "#FED7AA",
    "pill_low_bg": "#334155",
    "pill_low_fg": "#CBD5E1",
}


def table_style_tokens() -> dict[str, str]:
    """Colors for Generate report tables (light / dark)."""
    return _TABLE_DARK if app_theme() == "dark" else _TABLE_LIGHT


def report_table_stylesheet() -> str:
    """QSS for card-style QTableWidget (no Excel grid cage)."""
    t = table_style_tokens()
    return f"""
QTableWidget {{
    background: {t['surface']};
    color: {t['text']};
    border: 1px solid {t['border']};
    border-radius: 12px;
    gridline-color: transparent;
    outline: none;
    selection-background-color: {t['hover']};
    selection-color: {t['text']};
}}
QTableWidget::item {{
    padding: 6px 10px;
    border: none;
    border-bottom: 1px solid {t['hairline']};
}}
QTableWidget::item:selected {{
    background: {t['hover']};
    color: {t['text']};
}}
QHeaderView::section {{
    background: {t['header_bg']};
    color: {t['header_fg']};
    border: none;
    border-bottom: 1px solid {t['border']};
    border-right: none;
    padding: 8px 10px;
    font-weight: 600;
    font-size: 12px;
}}
QHeaderView::section:first {{
    border-top-left-radius: 11px;
}}
QHeaderView::section:last {{
    border-top-right-radius: 11px;
}}
QTableCornerButton::section {{
    background: {t['header_bg']};
    border: none;
    border-bottom: 1px solid {t['border']};
}}
QScrollBar:vertical {{
    background: {t['surface']};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t['border']};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


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

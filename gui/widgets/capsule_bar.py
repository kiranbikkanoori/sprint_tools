"""Horizontal capsule / pill tab bar used by app shell and Generate page."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QSizePolicy, QWidget

from gui.theme import capsule_stylesheet

# Stylesheet horizontal padding (16+16) + border + bold glyph slack.
_PAD_X = 40


class CapsuleBar(QWidget):
    """Exclusive checkable capsules. Emits ``currentChanged(index)``."""

    currentChanged = Signal(int)

    def __init__(self, labels: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: list[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        for i, label in enumerate(labels):
            btn = QPushButton(label)
            btn.setCheckable(True)
            # Keep the platform arrow cursor (no hand/pointer on hover).
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setMinimumHeight(32)
            self._group.addButton(btn, i)
            self._buttons.append(btn)
            row.addWidget(btn)

        row.addStretch(1)
        self._group.idClicked.connect(self._on_id)
        self.apply_theme()

        if self._buttons:
            self._buttons[0].setChecked(True)

    def apply_theme(self) -> None:
        """Refresh capsule colors for the current light/dark palette."""
        self.setStyleSheet(capsule_stylesheet())
        for btn in self._buttons:
            self._fit_button(btn)

    @staticmethod
    def _fit_button(btn: QPushButton) -> None:
        """Width follows label length using *selected* (semibold) metrics."""
        font = QFont(btn.font())
        font.setWeight(QFont.Weight.DemiBold)  # matches font-weight: 600
        fm = QFontMetrics(font)
        # boundingRect is safer than horizontalAdvance for first/last glyph overhang.
        text_w = fm.boundingRect(btn.text()).width()
        btn.setMinimumWidth(text_w + _PAD_X)
        btn.setFixedWidth(text_w + _PAD_X)

    def _on_id(self, idx: int) -> None:
        self.currentChanged.emit(idx)

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            # Block signals so callers can sync a stack without re-entry loops.
            self._group.blockSignals(True)
            self._buttons[index].setChecked(True)
            self._group.blockSignals(False)

    def current_index(self) -> int:
        return self._group.checkedId()

    def set_label(self, index: int, text: str) -> None:
        if 0 <= index < len(self._buttons):
            btn = self._buttons[index]
            btn.setText(text)
            self._fit_button(btn)

"""
Person × weekday leave checkbox grid for the Configure → Leaves tab.

Columns are sprint weekdays (Mon–Fri). A checked cell means that person is on
leave that day. Capacity uses the count of checked days.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config_parser import LeaveEntry, normalize_leave_entry
from utils import working_dates_in_range


class LeaveGrid(QWidget):
    """Editable leave matrix: rows = people, columns = sprint weekdays."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dates: list[date] = []
        self._names: list[str] = []
        self._notes_by_name: dict[str, str] = {}

        self.hint = QLabel(
            "Check a day to mark that person on leave. "
            "Capacity uses the number of checked weekdays. "
            "Weekend days are omitted."
        )
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #555;")

        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #555;")

        self.table = QTableWidget(0, 1)
        self.table.setHorizontalHeaderLabels(["Person"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.table)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.hint)
        layout.addWidget(scroll, stretch=1)
        layout.addWidget(self.summary)

        self.table.cellChanged.connect(self._update_summary)

    # ── public API ──────────────────────────────────────────────────────

    def set_sprint_range(self, start: date | None, end: date | None) -> None:
        """Rebuild weekday columns for ``[start, end]`` (inclusive)."""
        leaves = self.leave_entries()
        if start is None or end is None or end < start:
            self._dates = []
        else:
            self._dates = working_dates_in_range(start, end)
        self._rebuild_columns()
        self.set_people(self._names, preserve_leaves=leaves)

    def set_people(
        self,
        names: list[str],
        *,
        preserve_leaves: list[LeaveEntry] | None = None,
    ) -> None:
        """Set row people (included team members). Optionally keep current checks."""
        current = {
            e.name: e
            for e in (preserve_leaves if preserve_leaves is not None else self.leave_entries())
        }
        cleaned: list[str] = []
        seen: set[str] = set()
        for n in names:
            name = (n or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            cleaned.append(name)
        self._names = cleaned
        self._rebuild_rows(current)

    def set_leaves(self, entries: list[LeaveEntry]) -> None:
        by_name = {e.name: e for e in entries if (e.name or "").strip()}
        self._notes_by_name = {
            e.name: (e.notes or "") for e in by_name.values()
        }
        # Ensure people from leave entries appear even if not yet in team rows.
        names = list(self._names)
        for name in by_name:
            if name not in names:
                names.append(name)
        self.set_people(names, preserve_leaves=list(by_name.values()))

    def leave_entries(self) -> list[LeaveEntry]:
        """Return leave entries for people with at least one checked day."""
        out: list[LeaveEntry] = []
        for row, name in enumerate(self._names):
            dates: list[str] = []
            for col, d in enumerate(self._dates):
                w = self.table.cellWidget(row, col + 1)
                if w is None:
                    continue
                cb = w.findChild(QCheckBox)
                if cb is not None and cb.isChecked():
                    dates.append(d.isoformat())
            if not dates:
                continue
            out.append(
                normalize_leave_entry(
                    name=name,
                    dates=dates,
                    notes=self._notes_by_name.get(name, ""),
                )
            )
        return out

    # ── internals ───────────────────────────────────────────────────────

    def _rebuild_columns(self) -> None:
        self.table.blockSignals(True)
        self.table.setColumnCount(1 + len(self._dates))
        headers = ["Person"] + [d.strftime("%a %m/%d") for d in self._dates]
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setColumnWidth(0, 180)
        for col in range(1, self.table.columnCount()):
            self.table.setColumnWidth(col, 72)
        self.table.blockSignals(False)
        if not self._dates:
            self.summary.setText(
                "Load a sprint with start/end dates to enable the leave day grid."
            )
        else:
            self._update_summary()

    def _rebuild_rows(self, leaves_by_name: dict[str, LeaveEntry]) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._names))
        for row, name in enumerate(self._names):
            name_item = QTableWidgetItem(name)
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 0, name_item)
            entry = leaves_by_name.get(name)
            checked = set(entry.dates or []) if entry else set()
            for col, d in enumerate(self._dates):
                cell = QWidget()
                layout = QHBoxLayout(cell)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setAlignment(Qt.AlignCenter)
                cb = QCheckBox()
                cb.setChecked(d.isoformat() in checked)
                cb.stateChanged.connect(self._update_summary)
                layout.addWidget(cb)
                self.table.setCellWidget(row, col + 1, cell)
        self.table.blockSignals(False)
        self._update_summary()

    def _update_summary(self, *_args) -> None:
        if not self._dates:
            return
        parts: list[str] = []
        total = 0
        for row, name in enumerate(self._names):
            n = 0
            for col in range(len(self._dates)):
                w = self.table.cellWidget(row, col + 1)
                if w is None:
                    continue
                cb = w.findChild(QCheckBox)
                if cb is not None and cb.isChecked():
                    n += 1
            if n:
                parts.append(f"{name}: {n}d")
                total += n
        if parts:
            self.summary.setText(
                f"Leave selected — {total} person-day(s): " + "; ".join(parts)
            )
        else:
            self.summary.setText(
                f"{len(self._dates)} weekday columns · no leave days selected"
            )

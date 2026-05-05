"""
A small reusable editable table with Add / Remove buttons.

Used for Team Members, Leaves, Other Exclusions, Extra Tickets, Excluded
Tickets — each page configures the columns it needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


# ── Column descriptor ─────────────────────────────────────────────────────


@dataclass
class Column:
    key: str
    title: str
    kind: str = "text"           # "text" | "checkbox" | "number" | "combo"
    options: list | None = None  # for "combo"
    decimals: int = 1            # for "number"
    minimum: float = 0.0
    maximum: float = 999.0
    width: int | None = None
    placeholder: str = ""


# ── Combo delegate (so dropdown is editable inline) ───────────────────────


class _ComboDelegate(QStyledItemDelegate):
    def __init__(self, options_provider: Callable[[], list[str]], parent=None) -> None:
        super().__init__(parent)
        self._options_provider = options_provider

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        cb.setEditable(True)
        cb.addItems(self._options_provider())
        return cb

    def setEditorData(self, editor: QComboBox, index) -> None:
        text = index.model().data(index, Qt.EditRole) or ""
        i = editor.findText(text)
        if i >= 0:
            editor.setCurrentIndex(i)
        else:
            editor.setEditText(text)

    def setModelData(self, editor: QComboBox, model, index) -> None:
        model.setData(index, editor.currentText(), Qt.EditRole)


# ── Number delegate ───────────────────────────────────────────────────────


class _NumberDelegate(QStyledItemDelegate):
    def __init__(self, col: Column, parent=None) -> None:
        super().__init__(parent)
        self.col = col

    def createEditor(self, parent, option, index):
        sp = QDoubleSpinBox(parent)
        sp.setDecimals(self.col.decimals)
        sp.setRange(self.col.minimum, self.col.maximum)
        sp.setSingleStep(0.5 if self.col.decimals else 1)
        return sp

    def setEditorData(self, editor: QDoubleSpinBox, index) -> None:
        try:
            editor.setValue(float(index.model().data(index, Qt.EditRole) or 0))
        except (TypeError, ValueError):
            editor.setValue(0)

    def setModelData(self, editor: QDoubleSpinBox, model, index) -> None:
        editor.interpretText()
        val = editor.value()
        text = ("{:." + str(self.col.decimals) + "f}").format(val)
        if self.col.decimals == 0:
            text = str(int(val))
        else:
            text = text.rstrip("0").rstrip(".") or "0"
        model.setData(index, text, Qt.EditRole)


# ── Editable table widget ─────────────────────────────────────────────────


class EditableTable(QWidget):
    """
    Generic editable table.

    Use ``set_rows()`` to populate from data, ``rows()`` to read back as a
    list of dicts keyed by ``Column.key``.
    """

    def __init__(
        self,
        columns: list[Column],
        *,
        combo_options_provider: Optional[Callable[[], list[str]]] = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.columns = columns
        self._combo_options_provider = combo_options_provider or (lambda: [])

        self.table = QTableWidget(0, len(columns), self)
        self.table.setHorizontalHeaderLabels([c.title for c in columns])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked
            | QAbstractItemView.EditKeyPressed
        )
        self.table.setAlternatingRowColors(True)

        header = self.table.horizontalHeader()
        for i, col in enumerate(columns):
            if col.width:
                self.table.setColumnWidth(i, col.width)
                header.setSectionResizeMode(i, QHeaderView.Interactive)
            else:
                header.setSectionResizeMode(i, QHeaderView.Stretch)

        for i, col in enumerate(columns):
            if col.kind == "combo":
                self.table.setItemDelegateForColumn(
                    i, _ComboDelegate(self._combo_options_provider, self.table)
                )
            elif col.kind == "number":
                self.table.setItemDelegateForColumn(i, _NumberDelegate(col, self.table))

        self.btn_add = QPushButton("+ Add row")
        self.btn_remove = QPushButton("− Remove selected")
        self.btn_add.clicked.connect(self.add_row)
        self.btn_remove.clicked.connect(self._remove_selected)

        button_row = QHBoxLayout()
        button_row.addWidget(self.btn_add)
        button_row.addWidget(self.btn_remove)
        button_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(button_row)

    # ── public API ────────────────────────────────────────────────────────

    def set_rows(self, rows: list[dict]) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row in rows:
            self.add_row(row)
        self.table.blockSignals(False)

    def rows(self) -> list[dict]:
        out: list[dict] = []
        for r in range(self.table.rowCount()):
            row_data: dict[str, object] = {}
            for c, col in enumerate(self.columns):
                if col.kind == "checkbox":
                    holder = self.table.cellWidget(r, c)
                    cb = holder.findChild(QCheckBox) if holder else None
                    row_data[col.key] = bool(cb.isChecked()) if cb else False
                else:
                    item = self.table.item(r, c)
                    row_data[col.key] = item.text().strip() if item else ""
            out.append(row_data)
        return out

    def add_row(self, values: dict | None = None) -> None:
        values = values or {}
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, col in enumerate(self.columns):
            if col.kind == "checkbox":
                holder = QWidget(self.table)
                lay = QHBoxLayout(holder)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setAlignment(Qt.AlignCenter)
                cb = QCheckBox(holder)
                cb.setChecked(bool(values.get(col.key, True)))
                lay.addWidget(cb)
                self.table.setCellWidget(r, c, holder)
            else:
                v = values.get(col.key, "")
                item = QTableWidgetItem("" if v is None else str(v))
                if col.kind == "text" and col.placeholder and not v:
                    item.setForeground(Qt.gray)
                self.table.setItem(r, c, item)

    def _remove_selected(self) -> None:
        selected = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in selected:
            self.table.removeRow(r)

    def refresh_combos(self) -> None:
        """Force any open combo editors to pull fresh options."""
        for i, col in enumerate(self.columns):
            if col.kind == "combo":
                self.table.setItemDelegateForColumn(
                    i, _ComboDelegate(self._combo_options_provider, self.table)
                )

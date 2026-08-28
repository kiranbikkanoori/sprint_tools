"""Pick Jira boards and sprints into a presenter pack."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.pack_model import ReportPack
from gui.settings import AppSettings, save_settings
from gui.workers.jira_workers import (
    FetchBoardsWorker,
    FetchSprintDataWorker,
    FetchSprintListWorker,
    run_worker,
)

log = logging.getLogger(__name__)


class SprintSelectPage(QWidget):
    """Build a pack of board+sprint payloads. Emits ``sprint_added`` after each fetch."""

    sprint_added = Signal(dict, dict, dict)  # payload, sprint, board_meta
    configure_requested = Signal()

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._boards: list[dict] = []
        self._sprints: list[dict] = []
        self._pack = ReportPack()

        title = QLabel("<h2>Select board &amp; sprint</h2>")
        hint = QLabel(
            "Add one or more sprints to the pack, then continue to Configure. "
            "A single sprint works the same as before."
        )
        hint.setWordWrap(True)
        hint.setObjectName("sprintHint")
        self.hint = hint

        # ── Pack list ──
        pack_group = QGroupBox("Pack")
        pack_lay = QVBoxLayout(pack_group)
        self.pack_empty = QLabel("No sprints yet — pick a board and sprint, then Add sprint.")
        self.pack_empty.setWordWrap(True)
        self.pack_list = QListWidget()
        self.pack_list.setMinimumHeight(100)
        pack_btns = QHBoxLayout()
        self.remove_btn = QPushButton("Remove selected")
        self.remove_btn.setEnabled(False)
        pack_btns.addWidget(self.remove_btn)
        pack_btns.addStretch(1)
        pack_lay.addWidget(self.pack_empty)
        pack_lay.addWidget(self.pack_list)
        pack_lay.addLayout(pack_btns)

        # ── Board picker ──
        board_group = QGroupBox("Board")
        bg_form = QFormLayout(board_group)

        search_row = QHBoxLayout()
        self.board_query = QLineEdit()
        self.board_query.setPlaceholderText("Search boards (e.g. Wi-Fi LMAC)")
        self.board_query.setText(settings.last_board_name or "")
        self.search_btn = QPushButton("Search")
        search_row.addWidget(self.board_query)
        search_row.addWidget(self.search_btn)
        sw = QWidget()
        sw.setLayout(search_row)
        bg_form.addRow("Filter", sw)

        self.board_combo = QComboBox()
        self.board_combo.setMinimumWidth(360)
        bg_form.addRow("Board", self.board_combo)

        # ── Sprint picker ──
        sprint_group = QGroupBox("Sprint")
        sg_form = QFormLayout(sprint_group)
        self.sprint_combo = QComboBox()
        self.sprint_combo.setMinimumWidth(360)
        sg_form.addRow("Sprint", self.sprint_combo)
        self.sprint_meta = QLabel("")
        self.sprint_meta.setObjectName("sprintMeta")
        sg_form.addRow("", self.sprint_meta)

        # ── Actions / progress ──
        self.progress_label = QLabel("")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add sprint")
        self.add_btn.setDefault(True)
        self.add_btn.setEnabled(False)
        self.configure_btn = QPushButton("Configure →")
        self.configure_btn.setEnabled(False)
        btn_row.addWidget(self.add_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.configure_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.hint)
        layout.addWidget(pack_group)
        layout.addWidget(board_group)
        layout.addWidget(sprint_group)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)
        layout.addStretch(1)
        layout.addLayout(btn_row)

        self.search_btn.clicked.connect(self._search_boards)
        self.board_query.returnPressed.connect(self._search_boards)
        self.board_combo.currentIndexChanged.connect(self._on_board_changed)
        self.sprint_combo.currentIndexChanged.connect(self._on_sprint_changed)
        self.add_btn.clicked.connect(self._add_sprint)
        self.configure_btn.clicked.connect(self.configure_requested.emit)
        self.remove_btn.clicked.connect(self._remove_selected)
        self.pack_list.currentRowChanged.connect(
            lambda i: self.remove_btn.setEnabled(i >= 0)
        )

    # ── pack sync (MainWindow owns the model) ───────────────────────────

    def set_pack(self, pack: ReportPack) -> None:
        """Refresh the pack list from MainWindow's ReportPack."""
        self._pack = pack
        self.pack_list.clear()
        for slot in pack.slots:
            item = QListWidgetItem(slot.label)
            item.setToolTip(
                f"{len(slot.payload.get('issues', []))} issues · "
                f"board id {slot.board_id}"
            )
            self.pack_list.addItem(item)
        empty = len(pack) == 0
        self.pack_empty.setVisible(empty)
        self.pack_list.setVisible(not empty)
        self.configure_btn.setEnabled(not empty)
        self.remove_btn.setEnabled(self.pack_list.currentRow() >= 0)

    def _remove_selected(self) -> None:
        row = self.pack_list.currentRow()
        if row < 0:
            return
        self._pack.remove_at(row)
        self.set_pack(self._pack)

    # ── helpers ─────────────────────────────────────────────────────────

    def _busy(self, msg: str, busy: bool) -> None:
        self.progress_label.setText(msg if busy else "")
        self.progress_bar.setVisible(busy)
        self.search_btn.setEnabled(not busy)
        self.add_btn.setEnabled(
            not busy
            and self.sprint_combo.currentIndex() >= 0
            and self.sprint_combo.count() > 0
        )
        self.configure_btn.setEnabled(not busy and len(self._pack) > 0)
        self.remove_btn.setEnabled(not busy and self.pack_list.currentRow() >= 0)

    @Slot(str)
    def _show_error(self, msg: str) -> None:
        self._busy("", False)
        QMessageBox.critical(self, "Jira error", msg)

    # ── search / select ─────────────────────────────────────────────────

    def _search_boards(self) -> None:
        creds = self.settings.effective_credentials()
        if not creds.get("JIRA_BASE_URL"):
            QMessageBox.warning(
                self, "No connection", "Configure Jira credentials in Settings first."
            )
            return
        self._busy("Searching boards…", True)
        worker = FetchBoardsWorker(creds, self.board_query.text().strip())
        worker.finished.connect(
            self._on_boards_loaded, Qt.ConnectionType.QueuedConnection
        )
        worker.failed.connect(self._show_error, Qt.ConnectionType.QueuedConnection)
        run_worker(worker, self)

    @Slot(list)
    def _on_boards_loaded(self, boards: list) -> None:
        self._boards = boards or []
        self.board_combo.blockSignals(True)
        self.board_combo.clear()
        for b in self._boards:
            self.board_combo.addItem(f"{b.get('name', '?')}  (id {b.get('id')})", b)
        self.board_combo.blockSignals(False)

        if self.settings.last_board_id:
            for i, b in enumerate(self._boards):
                if b.get("id") == self.settings.last_board_id:
                    self.board_combo.setCurrentIndex(i)
                    break
        self._busy("", False)
        if not self._boards:
            QMessageBox.information(self, "No boards", "No matching boards found.")
        else:
            self._on_board_changed(self.board_combo.currentIndex())

    def _on_board_changed(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._boards):
            return
        board = self._boards[idx]
        creds = self.settings.effective_credentials()
        self._busy("Loading sprints…", True)
        self.sprint_combo.clear()
        self.sprint_meta.setText("")
        worker = FetchSprintListWorker(creds, board["id"])
        worker.finished.connect(
            self._on_sprints_loaded, Qt.ConnectionType.QueuedConnection
        )
        worker.failed.connect(self._show_error, Qt.ConnectionType.QueuedConnection)
        run_worker(worker, self)

    @Slot(list)
    def _on_sprints_loaded(self, sprints: list) -> None:
        actives = [s for s in sprints if s.get("state") == "active"]
        futures = [s for s in sprints if s.get("state") == "future"]
        closed = [s for s in sprints if s.get("state") == "closed"]
        ordered = actives + futures + list(reversed(closed))
        self._sprints = ordered

        self.sprint_combo.blockSignals(True)
        self.sprint_combo.clear()
        for s in ordered:
            label = f"[{s.get('state', '?'):6}] {s.get('name', '?')}"
            self.sprint_combo.addItem(label, s)
        self.sprint_combo.blockSignals(False)

        if self.settings.last_sprint_name:
            for i, s in enumerate(ordered):
                if s.get("name") == self.settings.last_sprint_name:
                    self.sprint_combo.setCurrentIndex(i)
                    break
        self._busy("", False)
        if ordered:
            self._on_sprint_changed(self.sprint_combo.currentIndex())

    def _on_sprint_changed(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._sprints):
            self.sprint_meta.setText("")
            self.add_btn.setEnabled(False)
            return
        s = self._sprints[idx]
        meta = (
            f"State: {s.get('state', '?')}  •  "
            f"Start: {(s.get('startDate') or '—')[:10]}  •  "
            f"End: {(s.get('endDate') or '—')[:10]}"
        )
        self.sprint_meta.setText(meta)
        self.add_btn.setEnabled(True)

    # ── fetch sprint payload ────────────────────────────────────────────

    def _add_sprint(self) -> None:
        log.info("Add sprint clicked")
        idx = self.sprint_combo.currentIndex()
        if idx < 0 or idx >= len(self._sprints):
            log.warning("No sprint selected (idx=%d, count=%d)", idx, len(self._sprints))
            return
        sprint = self._sprints[idx]
        board_idx = self.board_combo.currentIndex()
        board = self._boards[board_idx] if 0 <= board_idx < len(self._boards) else None
        log.info(
            "Adding sprint=%s, board=%s",
            sprint.get("name"),
            board.get("name") if board else None,
        )

        self.settings.last_sprint_name = sprint.get("name", "")
        if board:
            self.settings.last_board_id = int(board.get("id", 0))
            self.settings.last_board_name = board.get("name", "")
        save_settings(self.settings)

        creds = self.settings.effective_credentials()
        self._busy(f"Fetching {sprint.get('name', '')}…", True)
        self._pending_sprint = sprint
        self._pending_board = board or {}

        worker = FetchSprintDataWorker(creds, sprint)
        worker.progress.connect(
            self._on_progress, Qt.ConnectionType.QueuedConnection
        )
        worker.failed.connect(self._show_error, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(
            self._on_sprint_data_ready, Qt.ConnectionType.QueuedConnection
        )
        log.info("Spawning FetchSprintDataWorker thread")
        run_worker(worker, self)

    @Slot(str, int, int)
    def _on_progress(self, msg: str, cur: int, total: int) -> None:
        self.progress_label.setText(msg)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(cur)
        else:
            self.progress_bar.setRange(0, 0)

    @Slot(dict)
    def _on_sprint_data_ready(self, payload: dict) -> None:
        log.info("Sprint data ready: %d issues", len(payload.get("issues", [])))
        sprint = getattr(self, "_pending_sprint", {}) or {}
        board = getattr(self, "_pending_board", {}) or {}
        self._busy("", False)
        board_meta = {
            "id": int(board.get("id", 0) or 0),
            "name": str(board.get("name") or ""),
        }
        self.sprint_added.emit(payload, sprint, board_meta)

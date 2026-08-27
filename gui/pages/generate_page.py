"""Generate report outputs and review them in native capsule tabs."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config_parser import SprintConfig
from gui.report_view_model import ReportViewModel
from gui.settings import AppSettings, output_dir_default
from gui.theme import theme_colors, ticket_type_chips, overview_chip_style
from gui.widgets.capsule_bar import CapsuleBar
from gui.workers.jira_workers import GenerateReportWorker, run_worker

log = logging.getLogger(__name__)

_MAX_TICKETS_IN_CELL = 8

_TAB_OVERVIEW = 0
_TAB_HOURS = 1
_TAB_FIXUPS = 2
_TAB_TICKETS = 3
_TAB_KPIS = 4


class GeneratePage(QWidget):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.config: SprintConfig | None = None
        self.payload: dict = {}
        self.last_outputs: dict[str, Path] = {}
        self.view_model: ReportViewModel | None = None

        title = QLabel("<h2>Generate report</h2>")

        opts = QGroupBox("Output")
        o_lay = QHBoxLayout(opts)
        self.cb_report = QCheckBox("Report (Markdown + HTML)")
        self.cb_report.setChecked(True)
        o_lay.addWidget(self.cb_report)
        o_lay.addStretch(1)

        self.output_label = QLabel(f"Output folder: {settings.output_dir or output_dir_default()}")
        self.choose_dir_btn = QPushButton("Change…")
        out_row = QHBoxLayout()
        out_row.addWidget(self.output_label, stretch=1)
        out_row.addWidget(self.choose_dir_btn)
        self.choose_dir_btn.clicked.connect(self._choose_output_dir)

        actions = QHBoxLayout()
        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setDefault(True)
        self.open_html_btn = QPushButton("Open HTML report")
        self.open_html_btn.setEnabled(False)
        self.open_folder_btn = QPushButton("Open output folder")
        self.open_folder_btn.setEnabled(False)
        actions.addWidget(self.generate_btn)
        actions.addStretch(1)
        actions.addWidget(self.open_html_btn)
        actions.addWidget(self.open_folder_btn)

        self.generate_btn.clicked.connect(self._generate)
        self.open_html_btn.clicked.connect(self._open_html_report)
        self.open_folder_btn.clicked.connect(self._open_output_folder)

        self.progress_label = QLabel("")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)

        self.section_nav = CapsuleBar(
            ["Overview", "Hours", "Fix-ups", "Tickets", "KPIs"]
        )
        self.section_nav.currentChanged.connect(self._on_section)

        self.section_stack = QStackedWidget()
        self.overview_page = self._build_overview()
        self.hours_page = self._build_hours()
        self.fixups_page = self._build_fixups()
        self.tickets_page = self._build_tickets()
        self.kpis_page = self._build_kpis()
        self.section_stack.addWidget(self.overview_page)
        self.section_stack.addWidget(self.hours_page)
        self.section_stack.addWidget(self.fixups_page)
        self.section_stack.addWidget(self.tickets_page)
        self.section_stack.addWidget(self.kpis_page)

        self.placeholder = QLabel(
            "Load a sprint, configure the team, then click <b>Generate</b> "
            "to review Overview · Hours · Fix-ups · Tickets · KPIs."
        )
        self.placeholder.setWordWrap(True)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.review_host = QStackedWidget()
        self.review_host.addWidget(self.placeholder)  # 0
        review = QWidget()
        rev_lay = QVBoxLayout(review)
        rev_lay.setContentsMargins(0, 0, 0, 0)
        rev_lay.addWidget(self.section_nav)
        rev_lay.addWidget(self.section_stack, stretch=1)
        self.review_host.addWidget(review)  # 1

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(opts)
        layout.addLayout(out_row)
        layout.addLayout(actions)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.review_host, stretch=1)

        self.apply_theme()

    def apply_theme(self) -> None:
        """Refresh Generate UI colors for the current light/dark palette."""
        c = theme_colors()
        chips = ticket_type_chips()
        self.section_nav.apply_theme()
        self.placeholder.setStyleSheet(f"color: {c['muted']}; padding: 24px;")
        self.live_banner.setStyleSheet(
            f"background: {c['warn_bg']}; color: {c['warn_text']}; "
            f"border: 1px solid {c['border']}; border-radius: 8px; padding: 8px 12px;"
        )
        story_bg, story_fg = chips["story"]
        task_bg, task_fg = chips["task"]
        sub_bg, sub_fg = chips["subtask"]
        self.hours_legend.setText(
            f'<span style="background:{story_bg}; color:{story_fg}; '
            f'padding:2px 6px; border-radius:3px;"><b>Story</b></span> &nbsp; '
            f'<span style="background:{task_bg}; color:{task_fg}; '
            f'padding:2px 6px; border-radius:3px;"><b>Task / bug</b></span> &nbsp; '
            f'<span style="background:{sub_bg}; color:{sub_fg}; '
            f'padding:2px 6px; border-radius:3px;"><b>Sub-task ✗</b></span> '
            "· Each day lists ticket keys · click a cell for hours"
        )
        self.fixups_empty.setStyleSheet(f"color: {c['muted']}; padding: 16px;")
        self.tickets_note.setStyleSheet(f"color: {c['muted']};")
        self.kpis_intro.setStyleSheet(f"color: {c['muted']};")
        self.completion_note.setStyleSheet(f"color: {c['muted']};")
        if self.view_model is not None:
            self._populate_review(self.view_model)

    # ── section builders ────────────────────────────────────────────────

    def _build_overview(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.live_banner = QLabel(
            "Status and remaining are <b>as of this generate run</b>, "
            "not frozen at sprint end."
        )
        self.live_banner.setWordWrap(True)
        lay.addWidget(self.live_banner)

        self.chips_host = QWidget()
        self.chips_grid = QGridLayout(self.chips_host)
        self.chips_grid.setContentsMargins(0, 0, 0, 0)
        self.chips_grid.setHorizontalSpacing(10)
        self.chips_grid.setVerticalSpacing(10)
        lay.addWidget(self.chips_host)

        self.fixup_link = QLabel("")
        self.fixup_link.setTextFormat(Qt.TextFormat.RichText)
        self.fixup_link.linkActivated.connect(lambda _u: self._show_section(_TAB_FIXUPS))
        lay.addWidget(self.fixup_link)

        goal_label = QLabel("Sprint goal")
        goal_label.setStyleSheet("font-weight: 600;")
        lay.addWidget(goal_label)
        self.goal_edit = QTextEdit()
        self.goal_edit.setReadOnly(True)
        self.goal_edit.setMaximumHeight(160)
        lay.addWidget(self.goal_edit)
        lay.addStretch(1)
        return w

    def _build_hours(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.hours_legend = QLabel("")
        self.hours_legend.setTextFormat(Qt.TextFormat.RichText)
        self.hours_legend.setWordWrap(True)
        lay.addWidget(self.hours_legend)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.hours_table = QTableWidget()
        self.hours_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hours_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.hours_table.cellClicked.connect(self._on_hours_cell)
        split.addWidget(self.hours_table)

        self.hours_drawer = QTextEdit()
        self.hours_drawer.setReadOnly(True)
        self.hours_drawer.setPlaceholderText("Select a day cell to see ticket keys.")
        self.hours_drawer.setMinimumWidth(220)
        split.addWidget(self.hours_drawer)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, stretch=1)
        return w

    def _build_fixups(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.fixups_empty = QLabel("")
        self.fixups_empty.setWordWrap(True)
        self.fixups_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.fixups_empty)

        self.fixups_table = QTableWidget()
        self.fixups_table.setColumnCount(6)
        self.fixups_table.setHorizontalHeaderLabels(
            ["Severity", "Type", "Key", "Person", "Summary", "Why / what to do"]
        )
        self.fixups_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self.fixups_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        self.fixups_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fixups_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        lay.addWidget(self.fixups_table, stretch=1)

        jump = QHBoxLayout()
        for label, idx in (
            ("Overview", _TAB_OVERVIEW),
            ("Hours", _TAB_HOURS),
            ("Tickets", _TAB_TICKETS),
            ("KPIs", _TAB_KPIS),
        ):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, i=idx: self._show_section(i))
            jump.addWidget(b)
        jump.addStretch(1)
        lay.addLayout(jump)
        return w

    def _build_tickets(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.tickets_note = QLabel(
            "Status and remaining are as of this generate run (not sprint-end freeze)."
        )
        lay.addWidget(self.tickets_note)

        filt = QHBoxLayout()
        filt.addWidget(QLabel("Status"))
        self.ticket_status = QComboBox()
        self.ticket_status.addItem("All", "")
        filt.addWidget(self.ticket_status)
        filt.addWidget(QLabel("Assignee"))
        self.ticket_assignee = QComboBox()
        self.ticket_assignee.addItem("All", "")
        filt.addWidget(self.ticket_assignee)
        filt.addWidget(QLabel("Type"))
        self.ticket_type = QComboBox()
        self.ticket_type.addItem("All", "")
        self.ticket_type.addItem("Story", "Story")
        self.ticket_type.addItem("Task", "Task")
        filt.addWidget(self.ticket_type)
        self.ticket_warn_only = QCheckBox("⚠ only")
        filt.addWidget(self.ticket_warn_only)
        filt.addStretch(1)
        lay.addLayout(filt)

        self.tickets_table = QTableWidget()
        self.tickets_table.setColumnCount(8)
        self.tickets_table.setHorizontalHeaderLabels(
            ["Key", "Summary", "Type", "Assignee", "Status", "Estimate (h)", "Remaining (h)", "SP"]
        )
        self.tickets_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.tickets_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tickets_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tickets_table.setSortingEnabled(True)
        lay.addWidget(self.tickets_table, stretch=1)

        for wdg in (self.ticket_status, self.ticket_assignee, self.ticket_type):
            wdg.currentIndexChanged.connect(self._apply_ticket_filters)
        self.ticket_warn_only.toggled.connect(self._apply_ticket_filters)
        return w

    def _build_kpis(self) -> QWidget:
        outer = QWidget()
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setSpacing(12)

        self.kpis_intro = QLabel(
            "Same Sprint KPI Summary and Completion & Velocity tables as the exported report."
        )
        self.kpis_intro.setWordWrap(True)
        lay.addWidget(self.kpis_intro)

        kpi_title = QLabel("<b>Sprint KPI Summary</b>")
        lay.addWidget(kpi_title)
        self.kpi_table = QTableWidget()
        self.kpi_table.setColumnCount(3)
        self.kpi_table.setHorizontalHeaderLabels(["KPI", "Value", "Notes"])
        self.kpi_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.kpi_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.kpi_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.kpi_table.verticalHeader().setVisible(False)
        lay.addWidget(self.kpi_table)

        cv_title = QLabel("<b>Sprint Completion &amp; Velocity</b>")
        lay.addWidget(cv_title)
        self.completion_note = QLabel(
            "Completion — Stories + Tasks done (Done/Complete category, or Resolved). "
            "Target ≥ 90%. Velocity — story points delivered ÷ effective person-days."
        )
        self.completion_note.setWordWrap(True)
        lay.addWidget(self.completion_note)

        team_title = QLabel("Team")
        team_title.setStyleSheet("font-weight: 600;")
        lay.addWidget(team_title)
        self.completion_team_table = QTableWidget()
        self.completion_team_table.setColumnCount(3)
        self.completion_team_table.setHorizontalHeaderLabels(["Metric", "Value", "Target"])
        self.completion_team_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.completion_team_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.completion_team_table.verticalHeader().setVisible(False)
        lay.addWidget(self.completion_team_table)

        person_title = QLabel("Per-person")
        person_title.setStyleSheet("font-weight: 600;")
        lay.addWidget(person_title)
        self.completion_people_table = QTableWidget()
        self.completion_people_table.setColumnCount(6)
        self.completion_people_table.setHorizontalHeaderLabels(
            [
                "Person",
                "Tickets done / committed",
                "Tickets %",
                "SP delivered / committed",
                "SP %",
                "SP / person-day",
            ]
        )
        self.completion_people_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.completion_people_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.completion_people_table.setSortingEnabled(True)
        self.completion_people_table.verticalHeader().setVisible(False)
        lay.addWidget(self.completion_people_table)
        lay.addStretch(1)

        scroll.setWidget(body)
        outer_lay.addWidget(scroll)
        return outer

    # ── public ──────────────────────────────────────────────────────────

    def set_inputs(self, config: SprintConfig, payload: dict) -> None:
        self.config = config
        self.payload = payload

    # ── handlers ────────────────────────────────────────────────────────

    def _choose_output_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Output folder", self.settings.output_dir or str(output_dir_default())
        )
        if d:
            self.settings.output_dir = d
            self.output_label.setText(f"Output folder: {d}")

    def _busy(self, msg: str, busy: bool) -> None:
        self.progress_label.setText(msg if busy else "")
        self.progress_bar.setVisible(busy)
        self.generate_btn.setEnabled(not busy)

    def _generate(self) -> None:
        if not self.config or not self.payload:
            QMessageBox.warning(
                self, "Nothing to generate", "Load a sprint and configure it first."
            )
            return
        out_dir = Path(self.settings.output_dir or output_dir_default())
        self._busy("Generating…", True)
        worker = GenerateReportWorker(
            self.config,
            self.payload,
            out_dir,
            make_report=self.cb_report.isChecked(),
            make_chart=False,
        )

        def _progress(msg, cur, total):
            self.progress_label.setText(msg)
            if total > 0:
                self.progress_bar.setRange(0, total)
                self.progress_bar.setValue(cur)
            else:
                self.progress_bar.setRange(0, 0)

        worker.progress.connect(_progress)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        run_worker(worker, self)

    def _on_failed(self, msg: str) -> None:
        self._busy("", False)
        QMessageBox.critical(self, "Generation failed", msg)

    def _on_finished(self, written: dict) -> None:
        self._busy("", False)
        written = written or {}
        self.view_model = written.pop("view_model", None)
        self.last_outputs = {k: Path(v) for k, v in written.items() if v is not None}
        self.open_folder_btn.setEnabled(bool(self.last_outputs))
        self.open_html_btn.setEnabled("report_html" in self.last_outputs)

        if self.view_model is not None:
            self._populate_review(self.view_model)
            self.review_host.setCurrentIndex(1)
            if self.view_model.default_tab == "fixups":
                self._show_section(_TAB_FIXUPS)
            else:
                self._show_section(_TAB_OVERVIEW)
        else:
            self.review_host.setCurrentIndex(0)

        msg = "Done."
        if "report_html" in self.last_outputs:
            msg += f"\n\nHTML report: {self.last_outputs['report_html']}"
        if "report" in self.last_outputs:
            msg += f"\nMarkdown : {self.last_outputs['report']}"
        QMessageBox.information(self, "Generated", msg)

    def _open_html_report(self) -> None:
        path = self.last_outputs.get("report_html")
        if not path or not path.is_file():
            QMessageBox.information(self, "No HTML report", "Generate a report first.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def _open_output_folder(self) -> None:
        out = self.settings.output_dir or str(output_dir_default())
        if sys.platform.startswith("win"):
            os.startfile(out)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", out])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def _on_section(self, index: int) -> None:
        self.section_stack.setCurrentIndex(index)

    def _show_section(self, index: int) -> None:
        self.section_nav.set_current(index)
        self.section_stack.setCurrentIndex(index)

    # ── populate tabs ───────────────────────────────────────────────────

    def _populate_review(self, vm: ReportViewModel) -> None:
        self._populate_overview(vm)
        self._populate_hours(vm)
        self._populate_fixups(vm)
        self._populate_tickets(vm)
        self._populate_kpis(vm)
        n = vm.fixup_count
        self.section_nav.set_label(_TAB_FIXUPS, f"Fix-ups ({n})" if n else "Fix-ups")

    def _populate_overview(self, vm: ReportViewModel) -> None:
        while self.chips_grid.count():
            item = self.chips_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, chip in enumerate(vm.chips):
            cs = overview_chip_style(chip.label)
            frame = QFrame()
            frame.setObjectName("overviewChip")
            frame.setStyleSheet(
                f"QFrame#overviewChip {{ background: {cs['bg']}; "
                f"border: 1px solid {cs['border']}; border-radius: 10px; }}"
                f"QFrame#overviewChip QLabel {{ background: transparent; border: none; }}"
            )
            row = QHBoxLayout(frame)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            stripe = QFrame()
            stripe.setFixedWidth(4)
            stripe.setStyleSheet(
                f"background: {cs['accent']}; border: none; "
                f"border-top-left-radius: 9px; border-bottom-left-radius: 9px;"
            )
            row.addWidget(stripe)
            content = QWidget()
            content.setStyleSheet("background: transparent; border: none;")
            fl = QVBoxLayout(content)
            fl.setContentsMargins(12, 10, 12, 10)
            fl.setSpacing(4)
            lab = QLabel(chip.label)
            lab.setWordWrap(True)
            lab.setStyleSheet(
                f"font-size: 13px; font-weight: 600; color: {cs['label']};"
            )
            fl.addWidget(lab)
            val = QLabel(chip.value)
            val.setStyleSheet(
                f"font-size: 22px; font-weight: 700; color: {cs['value']};"
            )
            fl.addWidget(val)
            if chip.detail:
                detail = QLabel(chip.detail)
                detail.setStyleSheet(f"font-size: 12px; color: {cs['detail']};")
                fl.addWidget(detail)
            row.addWidget(content, stretch=1)
            self.chips_grid.addWidget(frame, i // 4, i % 4)

        if vm.fixup_count:
            self.fixup_link.setText(
                f'<a href="#fixups">{vm.fixup_count} fix-up(s)</a> — open Fix-ups tab'
            )
        else:
            self.fixup_link.setText("No fix-ups — sprint looks clean on exception checks.")
        self.goal_edit.setPlainText(vm.sprint_goal or "(No sprint goal set in Jira.)")

    def _ticket_entries_for_day(
        self, detail: dict[str, dict[str, float]]
    ) -> list[tuple[str, str, float]]:
        """Flatten day ticket map → (key, bucket, hours) sorted by hours desc."""
        entries: list[tuple[str, str, float]] = []
        for bucket in ("story", "task", "subtask"):
            for key, hrs in (detail.get(bucket) or {}).items():
                if hrs >= 1e-6:
                    entries.append((key, bucket, float(hrs)))
        entries.sort(key=lambda x: (-x[2], x[0]))
        return entries

    def _make_day_cell_widget(
        self, entries: list[tuple[str, str, float]], total_h: float
    ) -> QWidget:
        host = QWidget()
        host.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay = QVBoxLayout(host)
        lay.setContentsMargins(3, 2, 3, 2)
        lay.setSpacing(2)
        c = theme_colors()
        chips = ticket_type_chips()

        if not entries:
            empty = QLabel("—")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {c['muted']};")
            lay.addWidget(empty)
            return host

        shown = entries[:_MAX_TICKETS_IN_CELL]
        for key, bucket, hrs in shown:
            bg, fg = chips.get(bucket, chips["task"])
            chip = QLabel(key)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setToolTip(f"{hrs:.1f}h · {bucket}")
            chip.setStyleSheet(
                f"background-color: {bg}; color: {fg}; border-radius: 4px; "
                f"padding: 2px 5px; font-size: 10px; font-weight: 600;"
            )
            lay.addWidget(chip)

        rest = len(entries) - len(shown)
        if rest > 0:
            more = QLabel(f"+{rest} more")
            more.setAlignment(Qt.AlignmentFlag.AlignCenter)
            more.setStyleSheet(f"color: {c['muted']}; font-size: 10px;")
            more.setToolTip(f"Total logged this day: {total_h:.1f}h")
            lay.addWidget(more)
        return host

    def _populate_hours(self, vm: ReportViewModel) -> None:
        dates = vm.display_dates
        cols = 1 + len(dates) + 3  # person + days + logged + rem + cap
        self.hours_table.clear()
        self.hours_table.setRowCount(len(vm.hours_rows) + 1)
        self.hours_table.setColumnCount(cols)
        headers = ["Person"] + [d.strftime("%b %d") for d in dates] + [
            "Logged (h)",
            "Remaining (h)",
            "Capacity (h)",
        ]
        self.hours_table.setHorizontalHeaderLabels(headers)

        team_logged = team_rem = team_cap = 0.0
        team_day = [0.0] * len(dates)

        for r_i, row in enumerate(vm.hours_rows):
            self.hours_table.setItem(r_i, 0, QTableWidgetItem(row.name))
            row_max = 1
            for c_i, d in enumerate(dates):
                cell = row.days.get(d)
                if cell is None:
                    s = t = x = 0.0
                else:
                    s, t, x = cell.story, cell.task, cell.subtask
                team_day[c_i] += s + t + x
                entries = self._ticket_entries_for_day(row.ticket_detail.get(d, {}))
                n_vis = min(len(entries), _MAX_TICKETS_IN_CELL)
                if len(entries) > _MAX_TICKETS_IN_CELL:
                    n_vis += 1
                row_max = max(row_max, n_vis)
                wdg = self._make_day_cell_widget(entries, s + t + x)
                self.hours_table.setCellWidget(r_i, 1 + c_i, wdg)
            self.hours_table.setItem(r_i, 1 + len(dates), QTableWidgetItem(f"{row.logged:.1f}"))
            self.hours_table.setItem(
                r_i, 2 + len(dates), QTableWidgetItem(f"{row.remaining:.1f}")
            )
            self.hours_table.setItem(
                r_i, 3 + len(dates), QTableWidgetItem(f"{row.capacity:.1f}")
            )
            # ~22px per chip + margins
            self.hours_table.setRowHeight(r_i, max(36, 8 + row_max * 22))
            team_logged += row.logged
            team_rem += row.remaining
            team_cap += row.capacity

        tot = len(vm.hours_rows)
        self.hours_table.setItem(tot, 0, QTableWidgetItem("Team total"))
        for c_i, v in enumerate(team_day):
            self.hours_table.setItem(tot, 1 + c_i, QTableWidgetItem(f"{v:.1f}"))
        self.hours_table.setItem(tot, 1 + len(dates), QTableWidgetItem(f"{team_logged:.1f}"))
        self.hours_table.setItem(tot, 2 + len(dates), QTableWidgetItem(f"{team_rem:.1f}"))
        self.hours_table.setItem(tot, 3 + len(dates), QTableWidgetItem(f"{team_cap:.1f}"))
        self.hours_table.resizeColumnsToContents()
        # Day columns need room for ticket keys
        for c_i in range(len(dates)):
            self.hours_table.setColumnWidth(1 + c_i, max(self.hours_table.columnWidth(1 + c_i), 110))
        self.hours_drawer.clear()

    def _on_hours_cell(self, row: int, col: int) -> None:
        vm = self.view_model
        if vm is None or row < 0 or row >= len(vm.hours_rows):
            return
        dates = vm.display_dates
        if col < 1 or col > len(dates):
            self.hours_drawer.setPlainText("Select a weekday cell to see ticket keys.")
            return
        person = vm.hours_rows[row]
        d = dates[col - 1]
        detail = person.ticket_detail.get(d, {})
        lines = [f"{person.name} — {d.strftime('%b %d, %Y')}", ""]
        for bucket, title in (
            ("story", "Stories (S)"),
            ("task", "Tasks (T)"),
            ("subtask", "Sub-tasks ✗ (not allowed)"),
        ):
            items = detail.get(bucket) or {}
            if not items:
                continue
            lines.append(title)
            for key, hrs in sorted(items.items(), key=lambda x: (-x[1], x[0])):
                lines.append(f"  • {key}  {hrs:.1f}h")
            lines.append("")
        if len(lines) <= 2:
            lines.append("(No ticket-level hours this day.)")
        self.hours_drawer.setPlainText("\n".join(lines))

    def _populate_fixups(self, vm: ReportViewModel) -> None:
        empty = vm.fixup_count == 0
        self.fixups_empty.setVisible(empty)
        self.fixups_table.setVisible(not empty)
        if empty:
            self.fixups_empty.setTextFormat(Qt.TextFormat.RichText)
            self.fixups_empty.setText(
                "<b>No fix-ups — sprint looks clean.</b><br>"
                "Use Overview for the scorecard, KPIs for the full tables, "
                "Hours for load, Tickets for the full list."
            )
            self.fixups_table.setRowCount(0)
            return
        self.fixups_table.setRowCount(len(vm.fixups))
        c = theme_colors()
        high_fg = QColor(c["warn_strong"])
        med_fg = QColor(c["warn_text"])
        for i, f in enumerate(vm.fixups):
            vals = [f.severity, f.type_label, f.key, f.person, f.summary, f.action]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if col == 0 and f.severity == "High":
                    item.setForeground(high_fg)
                    font = QFont()
                    font.setBold(True)
                    item.setFont(font)
                elif col == 0 and f.severity == "Med":
                    item.setForeground(med_fg)
                self.fixups_table.setItem(i, col, item)

    def _populate_tickets(self, vm: ReportViewModel) -> None:
        statuses = sorted({t.status for t in vm.tickets})
        assignees = sorted({t.assignee for t in vm.tickets})
        self.ticket_status.blockSignals(True)
        self.ticket_assignee.blockSignals(True)
        self.ticket_status.clear()
        self.ticket_status.addItem("All", "")
        for s in statuses:
            self.ticket_status.addItem(s, s)
        self.ticket_assignee.clear()
        self.ticket_assignee.addItem("All", "")
        for a in assignees:
            self.ticket_assignee.addItem(a, a)
        self.ticket_status.blockSignals(False)
        self.ticket_assignee.blockSignals(False)
        self._apply_ticket_filters()

    def _apply_ticket_filters(self) -> None:
        vm = self.view_model
        if vm is None:
            return
        st = self.ticket_status.currentData() or ""
        asg = self.ticket_assignee.currentData() or ""
        typ = self.ticket_type.currentData() or ""
        warn_only = self.ticket_warn_only.isChecked()

        rows = []
        for t in vm.tickets:
            if st and t.status != st:
                continue
            if asg and t.assignee != asg:
                continue
            if typ and t.type_ != typ:
                continue
            if warn_only and not t.has_warn:
                continue
            rows.append(t)

        # Keep not-done first even when sorting is enabled later
        rows.sort(key=lambda t: (t.is_done, t.status, t.key))

        self.tickets_table.setSortingEnabled(False)
        self.tickets_table.setRowCount(len(rows))
        c = theme_colors()
        warn_bg = QBrush(QColor(c["warn_bg"]))
        warn_fg = QColor(c["warn_strong"])
        warn_font = QFont()
        warn_font.setBold(True)
        rem_col = 6  # Remaining (h)
        for i, t in enumerate(rows):
            rem = "—" if t.remaining_hours is None else f"{t.remaining_hours:.1f}"
            if t.has_warn and t.remaining_hours is not None:
                rem = f"{t.remaining_hours:.1f} ⚠"
            vals = [
                t.key,
                t.summary,
                t.type_,
                t.assignee,
                t.status,
                f"{t.estimate_hours:.1f}",
                rem,
                f"{t.story_points:g}",
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if t.has_warn:
                    item.setBackground(warn_bg)
                    if col == rem_col:
                        item.setForeground(warn_fg)
                        item.setFont(warn_font)
                self.tickets_table.setItem(i, col, item)
        self.tickets_table.setSortingEnabled(True)

    def _populate_kpis(self, vm: ReportViewModel) -> None:
        # Sprint KPI Summary
        self.kpi_table.setRowCount(len(vm.kpi_rows))
        bold = QFont()
        bold.setBold(True)
        for i, row in enumerate(vm.kpi_rows):
            emphasize = row.label in (
                "Sprint completion rate",
                "Sprint velocity",
            )
            for col, text in enumerate((row.label, row.value, row.notes)):
                item = QTableWidgetItem(text)
                if emphasize and col <= 1:
                    item.setFont(bold)
                self.kpi_table.setItem(i, col, item)
        self.kpi_table.resizeColumnsToContents()
        self.kpi_table.setColumnWidth(2, max(280, self.kpi_table.columnWidth(2)))

        # Team completion
        self.completion_team_table.setRowCount(len(vm.completion_team))
        for i, row in enumerate(vm.completion_team):
            for col, text in enumerate((row.metric, row.value, row.target)):
                item = QTableWidgetItem(text)
                if row.emphasize and col <= 1:
                    item.setFont(bold)
                if col >= 1:
                    item.setTextAlignment(
                        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    )
                self.completion_team_table.setItem(i, col, item)
        self.completion_team_table.resizeColumnsToContents()

        # Per-person
        self.completion_people_table.setSortingEnabled(False)
        self.completion_people_table.setRowCount(len(vm.completion_people))
        for i, row in enumerate(vm.completion_people):
            vals = [
                row.name,
                row.tickets_frac,
                row.ticket_pct,
                row.sp_frac,
                row.sp_pct,
                row.velocity,
            ]
            for col, text in enumerate(vals):
                item = QTableWidgetItem(text)
                if col >= 2:
                    item.setTextAlignment(
                        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    )
                self.completion_people_table.setItem(i, col, item)
        self.completion_people_table.resizeColumnsToContents()
        self.completion_people_table.setSortingEnabled(True)

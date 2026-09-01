"""Generate report outputs and review them in native capsule tabs."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QFontMetrics
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
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.pack_model import ReportPack
from gui.report_view_model import ReportViewModel
from gui.settings import AppSettings, output_dir_default
from gui.theme import (
    overview_chip_style,
    report_table_stylesheet,
    table_style_tokens,
    theme_colors,
    ticket_type_chips,
)
from gui.widgets.capsule_bar import CapsuleBar
from gui.workers.jira_workers import GeneratePackWorker, run_worker

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
        self.pack = ReportPack()
        self.last_outputs: dict[str, Path] = {}
        self.last_html_paths: list[Path] = []
        self.view_models: list[tuple[str, ReportViewModel]] = []
        self._ticket_sections: list[tuple[ReportViewModel, QTableWidget]] = []
        self._styled_tables: list[QTableWidget] = []

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
            "Add sprint(s) on the Sprint tab, configure the team, then click <b>Generate</b> "
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
            "· Each day lists ticket keys with hours logged"
        )
        self.tickets_note.setStyleSheet(f"color: {c['muted']};")
        self.kpis_intro.setStyleSheet(f"color: {c['muted']};")
        self._style_report_tables()
        if self.view_models:
            self._populate_review(self.view_models)

    def _style_report_tables(self) -> None:
        """Apply card-style QSS to all report tables currently on screen."""
        qss = report_table_stylesheet()
        for table in self._styled_tables:
            try:
                table.setShowGrid(False)
                table.setStyleSheet(qss)
                table.verticalHeader().setVisible(False)
                table.setFrameShape(QFrame.Shape.NoFrame)
                hh = table.horizontalHeader()
                hh.setHighlightSections(False)
                hh.setDefaultAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
            except RuntimeError:
                pass

    def _register_table(self, table: QTableWidget) -> QTableWidget:
        self._styled_tables.append(table)
        qss = report_table_stylesheet()
        table.setShowGrid(False)
        table.setStyleSheet(qss)
        table.verticalHeader().setVisible(False)
        table.setFrameShape(QFrame.Shape.NoFrame)
        hh = table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        return table

    # ── section builders ────────────────────────────────────────────────

    def _make_scroll_host(self) -> tuple[QWidget, QVBoxLayout]:
        outer = QWidget()
        outer_lay = QVBoxLayout(outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setSpacing(16)
        lay.setContentsMargins(0, 0, 4, 0)
        scroll.setWidget(body)
        outer_lay.addWidget(scroll)
        return outer, lay

    def _build_overview(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.live_banner = QLabel(
            "Status and remaining are <b>as of this generate run</b>, "
            "not frozen at sprint end."
        )
        self.live_banner.setWordWrap(True)
        lay.addWidget(self.live_banner)
        host, self.overview_sections = self._make_scroll_host()
        lay.addWidget(host, stretch=1)
        return w

    def _build_hours(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.hours_legend = QLabel("")
        self.hours_legend.setTextFormat(Qt.TextFormat.RichText)
        self.hours_legend.setWordWrap(True)
        lay.addWidget(self.hours_legend)
        host, self.hours_sections = self._make_scroll_host()
        lay.addWidget(host, stretch=1)
        return w

    def _build_fixups(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        host, self.fixups_sections = self._make_scroll_host()
        lay.addWidget(host, stretch=1)

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

        host, self.tickets_sections = self._make_scroll_host()
        lay.addWidget(host, stretch=1)

        for wdg in (self.ticket_status, self.ticket_assignee, self.ticket_type):
            wdg.currentIndexChanged.connect(self._apply_ticket_filters)
        self.ticket_warn_only.toggled.connect(self._apply_ticket_filters)
        return w

    def _build_kpis(self) -> QWidget:
        outer, self.kpis_sections = self._make_scroll_host()
        # intro sits above sections via a wrapper
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        self.kpis_intro = QLabel(
            "Same Sprint KPI Summary and Completion & Velocity tables as the exported report."
        )
        self.kpis_intro.setWordWrap(True)
        lay.addWidget(self.kpis_intro)
        lay.addWidget(outer, stretch=1)
        return wrap

    # ── public ──────────────────────────────────────────────────────────

    def set_pack(self, pack: ReportPack) -> None:
        self.pack = pack

    def set_inputs(self, config, payload: dict) -> None:
        """Backward-compatible single-sprint entry (wraps as a one-slot pack)."""
        from gui.pack_model import PackSlot

        slot = PackSlot(
            board_id=int(getattr(self.settings, "last_board_id", 0) or 0),
            board_name=str(getattr(self.settings, "last_board_name", "") or ""),
            sprint={"name": getattr(config, "sprint_name", "")},
            payload=payload,
            config=config,
        )
        self.pack = ReportPack(slots=[slot])

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
        if len(self.pack) == 0:
            QMessageBox.warning(
                self, "Nothing to generate", "Add a sprint and configure it first."
            )
            return
        entries = []
        for slot in self.pack.slots:
            if slot.config is None or not slot.payload:
                QMessageBox.warning(
                    self,
                    "Incomplete pack",
                    f"Configure {slot.label} before generating.",
                )
                return
            entries.append((slot.label, slot.config, slot.payload))

        out_dir = Path(self.settings.output_dir or output_dir_default())
        self._busy(f"Generating 1/{len(entries)}…", True)
        worker = GeneratePackWorker(
            entries,
            out_dir,
            make_report=self.cb_report.isChecked(),
            make_chart=False,
        )
        # Must be QueuedConnection: nested callables are DirectConnection and
        # crash if they touch widgets from the worker thread (QPainter segfault).
        worker.progress.connect(
            self._on_generate_progress, Qt.ConnectionType.QueuedConnection
        )
        worker.failed.connect(self._on_failed, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._on_finished, Qt.ConnectionType.QueuedConnection)
        run_worker(worker, self)

    @Slot(str, int, int)
    def _on_generate_progress(self, msg: str, cur: int, total: int) -> None:
        self.progress_label.setText(msg)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(cur)
        else:
            self.progress_bar.setRange(0, 0)

    @Slot(str)
    def _on_failed(self, msg: str) -> None:
        self._busy("", False)
        QMessageBox.critical(self, "Generation failed", msg)

    @Slot(object)
    def _on_finished(self, results) -> None:
        self._busy("", False)
        results = results or []
        self.view_models = []
        self.last_html_paths = []
        self.last_outputs = {}
        for written in results:
            written = dict(written or {})
            label = str(written.pop("label", "") or "Sprint")
            vm = written.pop("view_model", None)
            if vm is not None:
                self.view_models.append((label, vm))
            for k, v in written.items():
                if v is None:
                    continue
                path = Path(v)
                self.last_outputs[f"{label}:{k}"] = path
                if k == "report_html":
                    self.last_html_paths.append(path)
        if self.last_html_paths:
            self.last_outputs["report_html"] = self.last_html_paths[0]

        self.open_folder_btn.setEnabled(bool(self.last_outputs))
        self.open_html_btn.setEnabled(bool(self.last_html_paths))

        if self.view_models:
            self._populate_review(self.view_models)
            self.review_host.setCurrentIndex(1)
            any_fixups = any(vm.fixup_count > 0 for _, vm in self.view_models)
            if any_fixups:
                self._show_section(_TAB_FIXUPS)
            else:
                self._show_section(_TAB_OVERVIEW)
        else:
            self.review_host.setCurrentIndex(0)

        msg = f"Done — {len(self.view_models)} sprint report(s)."
        for p in self.last_html_paths:
            msg += f"\n\nHTML: {p}"
        QMessageBox.information(self, "Generated", msg)

    def _open_html_report(self) -> None:
        if not self.last_html_paths:
            QMessageBox.information(self, "No HTML report", "Generate a report first.")
            return
        path = self.last_html_paths[0]
        if not path.is_file():
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

    # ── helpers ─────────────────────────────────────────────────────────

    def _clear_layout(self, lay: QVBoxLayout) -> None:
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _section_header(self, label: str) -> QFrame:
        t = table_style_tokens()
        band = QFrame()
        band.setObjectName("packSectionHeader")
        band.setStyleSheet(
            f"QFrame#packSectionHeader {{ background: {t['header_bg']}; "
            f"border: 1px solid {t['border']}; border-radius: 10px; }}"
        )
        row = QHBoxLayout(band)
        row.setContentsMargins(14, 10, 14, 10)
        lab = QLabel(label)
        lab.setStyleSheet(
            f"font-size: 15px; font-weight: 700; color: {t['header_fg']}; "
            f"background: transparent; border: none;"
        )
        row.addWidget(lab)
        row.addStretch(1)
        return band

    # ── populate tabs ───────────────────────────────────────────────────

    def _populate_review(self, items: list[tuple[str, ReportViewModel]]) -> None:
        self._styled_tables = []
        self._ticket_sections = []
        self._clear_layout(self.overview_sections)
        self._clear_layout(self.hours_sections)
        self._clear_layout(self.fixups_sections)
        self._clear_layout(self.tickets_sections)
        self._clear_layout(self.kpis_sections)

        for label, vm in items:
            self._add_overview_section(label, vm)
            self._add_hours_section(label, vm)
            self._add_fixups_section(label, vm)
            self._add_tickets_section(label, vm)
            self._add_kpis_section(label, vm)

        self._refresh_ticket_filter_options()
        self._apply_ticket_filters()

        total_fixups = sum(vm.fixup_count for _, vm in items)
        self.section_nav.set_label(
            _TAB_FIXUPS, f"Fix-ups ({total_fixups})" if total_fixups else "Fix-ups"
        )
        self.overview_sections.addStretch(1)
        self.hours_sections.addStretch(1)
        self.fixups_sections.addStretch(1)
        self.tickets_sections.addStretch(1)
        self.kpis_sections.addStretch(1)

    def _add_overview_section(self, label: str, vm: ReportViewModel) -> None:
        section = QWidget()
        lay = QVBoxLayout(section)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(10)
        lay.addWidget(self._section_header(label))

        chips_host = QWidget()
        chips_grid = QGridLayout(chips_host)
        chips_grid.setContentsMargins(0, 0, 0, 0)
        chips_grid.setHorizontalSpacing(10)
        chips_grid.setVerticalSpacing(10)
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
            chips_grid.addWidget(frame, i // 4, i % 4)
        lay.addWidget(chips_host)

        fixup_link = QLabel("")
        fixup_link.setTextFormat(Qt.TextFormat.RichText)
        fixup_link.linkActivated.connect(lambda _u: self._show_section(_TAB_FIXUPS))
        if vm.fixup_count:
            fixup_link.setText(
                f'<a href="#fixups">{vm.fixup_count} fix-up(s)</a> — open Fix-ups tab'
            )
        else:
            fixup_link.setText("No fix-ups — sprint looks clean on exception checks.")
        lay.addWidget(fixup_link)

        goal_label = QLabel("Sprint goal")
        goal_label.setStyleSheet("font-weight: 600;")
        lay.addWidget(goal_label)
        goal_edit = QTextEdit()
        goal_edit.setReadOnly(True)
        goal_edit.setMaximumHeight(120)
        goal_edit.setPlainText(vm.sprint_goal or "(No sprint goal set in Jira.)")
        lay.addWidget(goal_edit)
        self.overview_sections.addWidget(section)

    def _ticket_entries_for_day(
        self, detail: dict[str, dict[str, float]]
    ) -> list[tuple[str, str, float]]:
        entries: list[tuple[str, str, float]] = []
        for bucket in ("story", "task", "subtask"):
            for key, hrs in (detail.get(bucket) or {}).items():
                if hrs >= 1e-6:
                    entries.append((key, bucket, float(hrs)))
        entries.sort(key=lambda x: (-x[2], x[0]))
        return entries

    def _fit_table_columns(
        self,
        table: QTableWidget,
        *,
        stretch: list[int] | None = None,
        mins: dict[int, int] | None = None,
        slack: int = 20,
    ) -> None:
        stretch = stretch or []
        mins = mins or {}
        header = table.horizontalHeader()
        header.setMinimumSectionSize(48)
        measure = QFont(table.font())
        measure.setWeight(QFont.Weight.DemiBold)
        fm = QFontMetrics(measure)

        for c in range(table.columnCount()):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        table.resizeColumnsToContents()

        for c in range(table.columnCount()):
            if c in stretch:
                header.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
                continue
            content_w = table.columnWidth(c)
            hdr_item = table.horizontalHeaderItem(c)
            hdr_w = fm.boundingRect(hdr_item.text()).width() + 32 if hdr_item else 0
            longest = hdr_w
            for r in range(table.rowCount()):
                item = table.item(r, c)
                if item is not None and item.text():
                    longest = max(longest, fm.boundingRect(item.text()).width() + 28)
                wdg = table.cellWidget(r, c)
                if wdg is not None:
                    longest = max(longest, wdg.sizeHint().width() + 12)
            width = max(content_w + slack, longest, mins.get(c, 0))
            table.setColumnWidth(c, width)
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)

    def _make_day_cell_widget(
        self, entries: list[tuple[str, str, float]], total_h: float
    ) -> QWidget:
        host = QWidget()
        host.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay = QVBoxLayout(host)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        c = theme_colors()
        chips = ticket_type_chips()

        chip_font = QFont()
        chip_font.setPointSize(10)
        chip_font.setWeight(QFont.Weight.DemiBold)
        fm = QFontMetrics(chip_font)

        if not entries:
            empty = QLabel("—")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {c['muted']};")
            lay.addWidget(empty)
            return host

        shown = entries[:_MAX_TICKETS_IN_CELL]
        for key, bucket, hrs in shown:
            bg, fg = chips.get(bucket, chips["task"])
            label = f"{key} ({hrs:.1f}h)"
            chip = QLabel(label)
            chip.setFont(chip_font)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setToolTip(f"{hrs:.1f}h · {bucket}")
            text_w = fm.boundingRect(label).width()
            chip.setMinimumWidth(text_w + 18)
            chip.setMinimumHeight(fm.height() + 10)
            chip.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            chip.setStyleSheet(
                f"background-color: {bg}; color: {fg}; border-radius: 4px; "
                f"padding: 3px 8px; font-size: 10px; font-weight: 600;"
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

    def _add_hours_section(self, label: str, vm: ReportViewModel) -> None:
        section = QWidget()
        lay = QVBoxLayout(section)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(8)
        lay.addWidget(self._section_header(label))

        table = self._register_table(QTableWidget())
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        table.setTextElideMode(Qt.TextElideMode.ElideNone)

        dates = vm.display_dates
        cols = 1 + len(dates) + 3
        table.setRowCount(len(vm.hours_rows) + 1)
        table.setColumnCount(cols)
        headers = ["Person"] + [d.strftime("%b %d") for d in dates] + [
            "Logged (h)",
            "Remaining (h)",
            "Capacity (h)",
        ]
        table.setHorizontalHeaderLabels(headers)

        team_logged = team_rem = team_cap = 0.0
        team_day = [0.0] * len(dates)

        for r_i, row in enumerate(vm.hours_rows):
            table.setItem(r_i, 0, QTableWidgetItem(row.name))
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
                table.setCellWidget(r_i, 1 + c_i, wdg)
            table.setItem(r_i, 1 + len(dates), QTableWidgetItem(f"{row.logged:.1f}"))
            table.setItem(r_i, 2 + len(dates), QTableWidgetItem(f"{row.remaining:.1f}"))
            table.setItem(r_i, 3 + len(dates), QTableWidgetItem(f"{row.capacity:.1f}"))
            table.setRowHeight(r_i, max(44, 12 + row_max * 28))
            team_logged += row.logged
            team_rem += row.remaining
            team_cap += row.capacity

        tot = len(vm.hours_rows)
        t = table_style_tokens()
        total_bg = QBrush(QColor(t["total_bg"]))
        total_fg = QColor(t["total_fg"])
        bold = QFont()
        bold.setBold(True)
        name_item = QTableWidgetItem("Team total")
        name_item.setBackground(total_bg)
        name_item.setForeground(total_fg)
        name_item.setFont(bold)
        table.setItem(tot, 0, name_item)
        for c_i, v in enumerate(team_day):
            item = QTableWidgetItem(f"{v:.1f}")
            item.setBackground(total_bg)
            item.setForeground(total_fg)
            item.setFont(bold)
            item.setTextAlignment(
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            )
            table.setItem(tot, 1 + c_i, item)
        for col, val in (
            (1 + len(dates), team_logged),
            (2 + len(dates), team_rem),
            (3 + len(dates), team_cap),
        ):
            item = QTableWidgetItem(f"{val:.1f}")
            item.setBackground(total_bg)
            item.setForeground(total_fg)
            item.setFont(bold)
            item.setTextAlignment(
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            )
            table.setItem(tot, col, item)
        for r_i, row in enumerate(vm.hours_rows):
            for col in (1 + len(dates), 2 + len(dates), 3 + len(dates)):
                it = table.item(r_i, col)
                if it is not None:
                    it.setTextAlignment(
                        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    )
            name_it = table.item(r_i, 0)
            if name_it is not None:
                font = QFont()
                font.setBold(True)
                name_it.setFont(font)
        n_dates = len(dates)
        self._fit_table_columns(
            table,
            stretch=[],
            mins={
                **{1 + i: 148 for i in range(n_dates)},
                0: 100,
                1 + n_dates: 88,
                2 + n_dates: 100,
                3 + n_dates: 96,
            },
            slack=16,
        )
        table.setMinimumHeight(min(420, 56 + table.rowCount() * 48))
        lay.addWidget(table)

        # Missing weekdays (0h story+task) — leave-day exclusion later.
        miss_title = QLabel("Missing weekdays (no story/task hours logged)")
        miss_title.setStyleSheet("font-weight: 600;")
        lay.addWidget(miss_title)
        if not vm.missing_log_days:
            empty = QLabel("No missing weekdays — everyone logged on each weekday.")
            empty.setStyleSheet(f"color: {theme_colors()['muted']};")
            empty.setWordWrap(True)
            lay.addWidget(empty)
        else:
            miss = self._register_table(QTableWidget())
            miss.setColumnCount(2)
            miss.setHorizontalHeaderLabels(["Person", "Missing weekdays"])
            miss.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            miss.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            miss.setTextElideMode(Qt.TextElideMode.ElideNone)
            miss.setWordWrap(False)
            miss.setRowCount(len(vm.missing_log_days))
            for i, row in enumerate(vm.missing_log_days):
                name_it = QTableWidgetItem(row.name)
                font = QFont()
                font.setBold(True)
                name_it.setFont(font)
                miss.setItem(i, 0, name_it)
                miss.setItem(i, 1, QTableWidgetItem(row.missing_labels))
                miss.setRowHeight(i, 36)
            self._fit_table_columns(miss, stretch=[1], mins={0: 120}, slack=16)
            miss.setMinimumHeight(min(280, 48 + miss.rowCount() * 36))
            lay.addWidget(miss)

        self.hours_sections.addWidget(section)

    def _severity_pill(self, severity: str) -> QWidget:
        t = table_style_tokens()
        sev = (severity or "").strip() or "—"
        if sev == "High":
            bg, fg = t["pill_high_bg"], t["pill_high_fg"]
        elif sev == "Med":
            bg, fg = t["pill_med_bg"], t["pill_med_fg"]
        else:
            bg, fg = t["pill_low_bg"], t["pill_low_fg"]
        host = QWidget()
        lay = QHBoxLayout(host)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lab = QLabel(sev)
        font = QFont()
        font.setPointSize(11)
        font.setWeight(QFont.Weight.Bold)
        lab.setFont(font)
        fm = QFontMetrics(font)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setMinimumWidth(fm.boundingRect(sev).width() + 20)
        lab.setMinimumHeight(fm.height() + 10)
        lab.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lab.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 11px; "
            f"padding: 4px 12px; font-size: 11px; font-weight: 700;"
        )
        lay.addWidget(lab)
        lay.addStretch(1)
        host.setMinimumHeight(fm.height() + 18)
        return host

    def _add_fixups_section(self, label: str, vm: ReportViewModel) -> None:
        c = theme_colors()
        section = QWidget()
        lay = QVBoxLayout(section)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(8)
        lay.addWidget(self._section_header(label))

        start_line = QLabel(
            f"Sprint started (IST): <b>{vm.sprint_started_ist or '—'}</b>"
        )
        start_line.setTextFormat(Qt.TextFormat.RichText)
        start_line.setStyleSheet(f"color: {c['muted']};")
        lay.addWidget(start_line)

        if vm.fixup_count == 0:
            empty = QLabel(
                "<b>No fix-ups — sprint looks clean.</b><br>"
                "Use Overview for the scorecard, KPIs for the full tables, "
                "Hours for load, Tickets for the full list."
            )
            empty.setTextFormat(Qt.TextFormat.RichText)
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {c['muted']}; padding: 16px;")
            lay.addWidget(empty)
            self.fixups_sections.addWidget(section)
            return

        table = self._register_table(QTableWidget())
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels(
            [
                "Severity",
                "Type",
                "Key",
                "Person",
                "Summary",
                "Added to sprint (IST)",
                "Why / what to do",
            ]
        )
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setTextElideMode(Qt.TextElideMode.ElideNone)
        table.setWordWrap(False)
        table.setRowCount(len(vm.fixups))
        t = table_style_tokens()
        key_fg = QColor(t["key_fg"])
        muted = QColor(t["muted"])
        for i, f in enumerate(vm.fixups):
            pill = self._severity_pill(f.severity)
            table.setCellWidget(i, 0, pill)
            sev_item = QTableWidgetItem(f.severity)
            sev_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            sev_item.setForeground(QColor(0, 0, 0, 0))
            table.setItem(i, 0, sev_item)
            type_item = QTableWidgetItem(f.type_label)
            key_item = QTableWidgetItem(f.key)
            key_item.setForeground(key_fg)
            font = QFont()
            font.setBold(True)
            key_item.setFont(font)
            person_item = QTableWidgetItem(f.person)
            summary_item = QTableWidgetItem(f.summary)
            added = (f.added_to_sprint_ist or "").strip() or "—"
            added_item = QTableWidgetItem(added)
            if added == "—":
                added_item.setForeground(muted)
            action_item = QTableWidgetItem(f.action)
            action_item.setForeground(muted)
            table.setItem(i, 1, type_item)
            table.setItem(i, 2, key_item)
            table.setItem(i, 3, person_item)
            table.setItem(i, 4, summary_item)
            table.setItem(i, 5, added_item)
            table.setItem(i, 6, action_item)
            table.setRowHeight(i, 44)
        self._fit_table_columns(
            table,
            stretch=[4, 6],
            mins={0: 88, 1: 140, 2: 120, 3: 100, 5: 160},
            slack=18,
        )
        table.setMinimumHeight(min(360, 48 + table.rowCount() * 48))
        lay.addWidget(table)
        self.fixups_sections.addWidget(section)

    def _add_tickets_section(self, label: str, vm: ReportViewModel) -> None:
        section = QWidget()
        lay = QVBoxLayout(section)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(8)
        lay.addWidget(self._section_header(label))

        table = self._register_table(QTableWidget())
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels(
            ["Key", "Summary", "Type", "Assignee", "Status", "Estimate (h)", "Remaining (h)", "SP"]
        )
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSortingEnabled(True)
        table.setTextElideMode(Qt.TextElideMode.ElideNone)
        table.setWordWrap(False)
        table.setMinimumHeight(240)
        lay.addWidget(table)
        self._ticket_sections.append((vm, table))
        self.tickets_sections.addWidget(section)

    def _refresh_ticket_filter_options(self) -> None:
        statuses: set[str] = set()
        assignees: set[str] = set()
        for vm, _ in self._ticket_sections:
            statuses.update(t.status for t in vm.tickets)
            assignees.update(t.assignee for t in vm.tickets)
        self.ticket_status.blockSignals(True)
        self.ticket_assignee.blockSignals(True)
        cur_st = self.ticket_status.currentData() or ""
        cur_asg = self.ticket_assignee.currentData() or ""
        self.ticket_status.clear()
        self.ticket_status.addItem("All", "")
        for s in sorted(statuses):
            self.ticket_status.addItem(s, s)
        self.ticket_assignee.clear()
        self.ticket_assignee.addItem("All", "")
        for a in sorted(assignees):
            self.ticket_assignee.addItem(a, a)
        # restore if still present
        idx = self.ticket_status.findData(cur_st)
        if idx >= 0:
            self.ticket_status.setCurrentIndex(idx)
        idx = self.ticket_assignee.findData(cur_asg)
        if idx >= 0:
            self.ticket_assignee.setCurrentIndex(idx)
        self.ticket_status.blockSignals(False)
        self.ticket_assignee.blockSignals(False)

    def _apply_ticket_filters(self) -> None:
        st = self.ticket_status.currentData() or ""
        asg = self.ticket_assignee.currentData() or ""
        typ = self.ticket_type.currentData() or ""
        warn_only = self.ticket_warn_only.isChecked()
        t = table_style_tokens()
        warn_bg = QBrush(QColor(t["warn_bg"]))
        warn_fg = QColor(t["warn_fg"])
        key_fg = QColor(t["key_fg"])
        warn_font = QFont()
        warn_font.setBold(True)
        key_font = QFont()
        key_font.setBold(True)
        rem_col = 6

        for vm, table in self._ticket_sections:
            rows = []
            for tick in vm.tickets:
                if st and tick.status != st:
                    continue
                if asg and tick.assignee != asg:
                    continue
                if typ and tick.type_ != typ:
                    continue
                if warn_only and not tick.has_warn:
                    continue
                rows.append(tick)
            rows.sort(key=lambda x: (x.is_done, x.status, x.key))

            table.setSortingEnabled(False)
            table.setRowCount(len(rows))
            for i, tick in enumerate(rows):
                rem = "—" if tick.remaining_hours is None else f"{tick.remaining_hours:.1f}"
                if tick.has_warn and tick.remaining_hours is not None:
                    rem = f"{tick.remaining_hours:.1f} ⚠"
                vals = [
                    tick.key,
                    tick.summary,
                    tick.type_,
                    tick.assignee,
                    tick.status,
                    f"{tick.estimate_hours:.1f}",
                    rem,
                    f"{tick.story_points:g}",
                ]
                for col, v in enumerate(vals):
                    item = QTableWidgetItem(v)
                    if col == 0:
                        item.setForeground(key_fg)
                        item.setFont(key_font)
                    if col in (5, 6, 7):
                        item.setTextAlignment(
                            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                        )
                    if tick.has_warn:
                        item.setBackground(warn_bg)
                        if col == rem_col:
                            item.setForeground(warn_fg)
                            item.setFont(warn_font)
                    table.setItem(i, col, item)
            table.setSortingEnabled(True)
            self._fit_table_columns(
                table,
                stretch=[1],
                mins={
                    0: 120,
                    2: 72,
                    3: 110,
                    4: 100,
                    5: 100,
                    6: 110,
                    7: 48,
                },
                slack=18,
            )
            table.setMinimumHeight(min(400, 56 + max(1, table.rowCount()) * 36))

    def _add_kpis_section(self, label: str, vm: ReportViewModel) -> None:
        section = QWidget()
        lay = QVBoxLayout(section)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(10)
        lay.addWidget(self._section_header(label))

        t = table_style_tokens()
        key_fg = QColor(t["key_fg"])
        muted = QColor(t["muted"])
        bold = QFont()
        bold.setBold(True)
        c = theme_colors()

        lay.addWidget(QLabel("<b>Sprint KPI Summary</b>"))
        kpi_table = self._register_table(QTableWidget())
        kpi_table.setColumnCount(3)
        kpi_table.setHorizontalHeaderLabels(["KPI", "Value", "Notes"])
        kpi_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        kpi_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        kpi_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        kpi_table.setRowCount(len(vm.kpi_rows))
        for i, row in enumerate(vm.kpi_rows):
            emphasize = row.label in ("Sprint completion rate", "Sprint velocity")
            quiet = (row.value or "").upper() == "N/A"
            for col, text in enumerate((row.label, row.value, row.notes)):
                item = QTableWidgetItem(text)
                if quiet:
                    item.setForeground(muted)
                elif emphasize and col == 1:
                    item.setFont(bold)
                    item.setForeground(key_fg)
                elif emphasize and col == 0:
                    item.setFont(bold)
                if col == 2:
                    item.setForeground(muted)
                kpi_table.setItem(i, col, item)
        kpi_table.resizeColumnsToContents()
        kpi_table.setColumnWidth(2, max(280, kpi_table.columnWidth(2)))
        kpi_table.setMinimumHeight(min(280, 40 + kpi_table.rowCount() * 32))
        lay.addWidget(kpi_table)

        lay.addWidget(QLabel("<b>Sprint Completion &amp; Velocity</b>"))
        note = QLabel(
            "Completion — Stories + Tasks done (Done/Complete category, or Resolved). "
            "Target ≥ 90%. Velocity — story points delivered ÷ effective person-days."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {c['muted']};")
        lay.addWidget(note)

        team_title = QLabel("Team")
        team_title.setStyleSheet("font-weight: 600;")
        lay.addWidget(team_title)
        team_table = self._register_table(QTableWidget())
        team_table.setColumnCount(3)
        team_table.setHorizontalHeaderLabels(["Metric", "Value", "Target"])
        team_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        team_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        team_table.setRowCount(len(vm.completion_team))
        for i, row in enumerate(vm.completion_team):
            for col, text in enumerate((row.metric, row.value, row.target)):
                item = QTableWidgetItem(text)
                if row.emphasize and col <= 1:
                    item.setFont(bold)
                if row.emphasize and col == 1:
                    item.setForeground(key_fg)
                if col == 2:
                    item.setForeground(muted)
                if col >= 1:
                    item.setTextAlignment(
                        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    )
                team_table.setItem(i, col, item)
        team_table.resizeColumnsToContents()
        team_table.setMinimumHeight(40 + team_table.rowCount() * 32)
        lay.addWidget(team_table)

        person_title = QLabel("Per-person")
        person_title.setStyleSheet("font-weight: 600;")
        lay.addWidget(person_title)
        people_table = self._register_table(QTableWidget())
        people_table.setColumnCount(6)
        people_table.setHorizontalHeaderLabels(
            [
                "Person",
                "Tickets done / committed",
                "Tickets %",
                "SP delivered / committed",
                "SP %",
                "SP / person-day",
            ]
        )
        people_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        people_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        people_table.setSortingEnabled(True)
        people_table.setSortingEnabled(False)
        people_table.setRowCount(len(vm.completion_people))
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
                if col == 0:
                    font = QFont()
                    font.setBold(True)
                    item.setFont(font)
                if col >= 2:
                    item.setTextAlignment(
                        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    )
                people_table.setItem(i, col, item)
        people_table.resizeColumnsToContents()
        people_table.setSortingEnabled(True)
        people_table.setMinimumHeight(min(320, 48 + people_table.rowCount() * 32))
        lay.addWidget(people_table)
        self.kpis_sections.addWidget(section)

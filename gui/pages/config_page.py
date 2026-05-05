"""Configure team, leaves, exclusions, extra tickets, report options."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config_parser import (
    ExclusionEntry,
    ExtraTicket,
    LeaveEntry,
    SprintConfig,
    TeamMember,
)
from gui import config_io, jira_service
from gui.settings import AppSettings, configs_dir
from gui.widgets.editable_table import Column, EditableTable


class ConfigPage(QWidget):
    """Holds the SprintConfig editor.  Emits ``config_ready(cfg)`` on Next."""

    config_ready = Signal(object)

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.config: SprintConfig = SprintConfig()
        self.payload: dict = {}

        title = QLabel("<h2>Sprint configuration</h2>")
        self.subtitle = QLabel("Load a sprint first to populate this form.")
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet("color: #555;")

        # ── Sprint header ──
        header = QGroupBox("Sprint")
        h_form = QFormLayout(header)
        self.name_edit = QLineEdit()
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 8)
        self.duration_spin.setSuffix(" weeks")
        self.duration_spin.setValue(2)
        self.report_date = QDateEdit()
        self.report_date.setCalendarPopup(True)
        self.report_date.setDisplayFormat("yyyy-MM-dd")
        self.report_date.setSpecialValueText("(today)")
        self.report_date.setDate(QDate.currentDate())
        h_form.addRow("Sprint name", self.name_edit)
        h_form.addRow("Duration", self.duration_spin)
        h_form.addRow("Report date", self.report_date)

        # ── Capacity ──
        cap = QGroupBox("Capacity")
        c_form = QFormLayout(cap)
        self.meeting_spin = QDoubleSpinBox()
        self.meeting_spin.setRange(0, 14)
        self.meeting_spin.setDecimals(1)
        self.meeting_spin.setSingleStep(0.5)
        self.meeting_spin.setSuffix(" days")
        self.meeting_spin.setValue(1.0)
        c_form.addRow("Meeting / ceremony reserve", self.meeting_spin)

        # ── Tabs ──
        self.tabs = QTabWidget()

        self.team_table = EditableTable([
            Column("name", "Name"),
            Column("role", "Role", width=140),
            Column("included", "Include", kind="checkbox", width=80),
        ])
        self.tabs.addTab(self._wrap(self.team_table,
            "People assigned to issues in the sprint. Uncheck anyone who shouldn't be in the report (e.g. managers)."),
            "Team members")

        self.leaves_table = EditableTable(
            [
                Column("name", "Name", kind="combo"),
                Column("days", "Leave days", kind="number", width=120, decimals=1, maximum=30),
                Column("notes", "Notes"),
            ],
            combo_options_provider=self._included_names,
        )
        self.tabs.addTab(self._wrap(self.leaves_table,
            "Planned leave per person, in days. Reduces capacity."),
            "Leaves")

        self.excl_table = EditableTable(
            [
                Column("name", "Name", kind="combo"),
                Column("hours", "Hours excluded", kind="number", width=140, decimals=1, maximum=200),
                Column("reason", "Reason"),
            ],
            combo_options_provider=self._included_names,
        )
        self.tabs.addTab(self._wrap(self.excl_table,
            "Recurring non-sprint work (production support, mentoring, etc.) that reduces capacity."),
            "Other exclusions")

        self.exticket_table = EditableTable([
            Column("key", "Ticket key", width=140),
            Column("assignee", "Assignee", kind="combo"),
            Column("notes", "Notes"),
        ], combo_options_provider=self._included_names)
        self.tabs.addTab(self._wrap(self.exticket_table,
            "Tickets outside this sprint that should still be counted."),
            "Extra tickets")

        self.exclticket_table = EditableTable([
            Column("key", "Ticket key", kind="combo", width=180),
            Column("reason", "Reason"),
        ], combo_options_provider=self._sprint_ticket_keys)
        self.tabs.addTab(self._wrap(self.exclticket_table,
            "Tickets in the sprint that should NOT be counted (umbrella/tracking tickets, etc.)."),
            "Excluded tickets")

        # ── Report options ──
        opts = QGroupBox("Report options")
        o_form = QFormLayout(opts)
        self.cb_per_ticket = QCheckBox("Show per-ticket worklog details")
        self.cb_log_gaps = QCheckBox("Show daily log gaps")
        self.cb_per_ticket.setChecked(True)
        self.cb_log_gaps.setChecked(True)
        o_form.addRow(self.cb_per_ticket)
        o_form.addRow(self.cb_log_gaps)

        # ── Action row ──
        actions = QHBoxLayout()
        self.import_btn = QPushButton("Import .md…")
        self.export_btn = QPushButton("Export .md…")
        self.save_btn = QPushButton("Save config")
        self.next_btn = QPushButton("Generate →")
        self.next_btn.setDefault(True)
        actions.addWidget(self.import_btn)
        actions.addWidget(self.export_btn)
        actions.addStretch(1)
        actions.addWidget(self.save_btn)
        actions.addWidget(self.next_btn)

        self.import_btn.clicked.connect(self._import_md)
        self.export_btn.clicked.connect(self._export_md)
        self.save_btn.clicked.connect(self._save_json)
        self.next_btn.clicked.connect(self._on_next)

        self.team_table.table.itemChanged.connect(self._refresh_combos)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.subtitle)
        layout.addWidget(header)
        layout.addWidget(cap)
        layout.addWidget(self.tabs, stretch=1)
        layout.addWidget(opts)
        layout.addLayout(actions)

    # ── helpers ─────────────────────────────────────────────────────────

    def _wrap(self, table: EditableTable, hint: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lbl = QLabel(hint)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #555;")
        lay.addWidget(lbl)
        lay.addWidget(table)
        return w

    def _included_names(self) -> list[str]:
        names = []
        for row in self.team_table.rows():
            n = (row.get("name") or "").strip()
            if n and row.get("included"):
                names.append(n)
        return names

    def _sprint_ticket_keys(self) -> list[str]:
        return jira_service.ticket_keys_in_payload(self.payload)

    def _refresh_combos(self, *_):
        self.leaves_table.refresh_combos()
        self.excl_table.refresh_combos()
        self.exticket_table.refresh_combos()

    # ── public entry: called after a sprint is loaded ───────────────────

    def populate_from_payload(self, payload: dict, sprint: dict) -> None:
        log.info("ConfigPage.populate_from_payload: sprint=%s", sprint.get("name"))
        self.payload = payload
        self.subtitle.setText(
            f"Sprint loaded: <b>{sprint.get('name', '')}</b> "
            f"({(sprint.get('startDate') or '')[:10]} → {(sprint.get('endDate') or '')[:10]}) — "
            f"{len(payload.get('issues', []))} issues."
        )
        cfg = SprintConfig()
        cfg.sprint_name = sprint.get("name", "")
        try:
            sd = date.fromisoformat((sprint.get("startDate") or "")[:10])
            ed = date.fromisoformat((sprint.get("endDate") or "")[:10])
            weeks = max(1, round((ed - sd).days / 7))
            cfg.sprint_duration_weeks = int(weeks)
        except Exception:
            cfg.sprint_duration_weeks = 2

        saved_path = configs_dir() / f"{cfg.sprint_name.replace(' ', '_')}.json"
        if saved_path.exists():
            try:
                cfg = config_io.load_json(saved_path)
            except Exception:  # noqa: BLE001
                pass

        existing_names = {m.name for m in cfg.team_members}
        for name in jira_service.assignees_in_payload(payload):
            if name not in existing_names:
                cfg.team_members.append(TeamMember(name=name, role="Developer", included=True))

        self.set_config(cfg)

        # Store the raw sprint dict for use in subtitle/display
        self._last_sprint_meta = sprint

    def set_config(self, cfg: SprintConfig) -> None:
        log.info("ConfigPage.set_config: %d members, %d leaves, %d exclusions",
                 len(cfg.team_members), len(cfg.planned_leaves), len(cfg.other_exclusions))
        self.config = cfg

        # Disconnect itemChanged during bulk population to avoid cascading
        # delegate refreshes (which can crash PySide6).
        try:
            self.team_table.table.itemChanged.disconnect(self._refresh_combos)
        except RuntimeError:
            pass

        self.name_edit.setText(cfg.sprint_name)
        self.duration_spin.setValue(int(cfg.sprint_duration_weeks or 2))
        if cfg.report_date:
            try:
                d = date.fromisoformat(cfg.report_date)
                self.report_date.setDate(QDate(d.year, d.month, d.day))
            except Exception:  # noqa: BLE001
                self.report_date.setDate(QDate.currentDate())
        else:
            self.report_date.setDate(QDate.currentDate())
        self.meeting_spin.setValue(float(cfg.meeting_days_reserved or 0))

        self.team_table.set_rows([
            {"name": m.name, "role": m.role, "included": m.included} for m in cfg.team_members
        ])
        self.leaves_table.set_rows([
            {"name": l.name, "days": l.days, "notes": l.notes} for l in cfg.planned_leaves
        ])
        self.excl_table.set_rows([
            {"name": e.name, "hours": e.hours, "reason": e.reason} for e in cfg.other_exclusions
        ])
        self.exticket_table.set_rows([
            {"key": t.key, "assignee": t.assignee, "notes": t.notes} for t in cfg.extra_tickets
        ])
        self.exclticket_table.set_rows([{"key": k, "reason": ""} for k in cfg.excluded_tickets])

        self.cb_per_ticket.setChecked(bool(cfg.show_per_ticket_details))
        self.cb_log_gaps.setChecked(bool(cfg.show_daily_log_gaps))

        # Reconnect after population is done.
        self.team_table.table.itemChanged.connect(self._refresh_combos)

    def gather_config(self) -> SprintConfig:
        cfg = SprintConfig()
        cfg.sprint_name = self.name_edit.text().strip()
        cfg.sprint_duration_weeks = int(self.duration_spin.value())
        cfg.meeting_days_reserved = float(self.meeting_spin.value())
        d = self.report_date.date()
        cfg.report_date = d.toString("yyyy-MM-dd") if d.isValid() else ""
        cfg.show_per_ticket_details = self.cb_per_ticket.isChecked()
        cfg.show_daily_log_gaps = self.cb_log_gaps.isChecked()

        cfg.team_members = [
            TeamMember(
                name=str(r.get("name", "")).strip(),
                role=str(r.get("role", "")).strip(),
                included=bool(r.get("included", True)),
            )
            for r in self.team_table.rows()
            if str(r.get("name", "")).strip()
        ]
        cfg.planned_leaves = [
            LeaveEntry(
                name=str(r.get("name", "")).strip(),
                days=_to_float(r.get("days")),
                notes=str(r.get("notes", "")).strip(),
            )
            for r in self.leaves_table.rows()
            if str(r.get("name", "")).strip()
        ]
        cfg.other_exclusions = [
            ExclusionEntry(
                name=str(r.get("name", "")).strip(),
                hours=_to_float(r.get("hours")),
                reason=str(r.get("reason", "")).strip(),
            )
            for r in self.excl_table.rows()
            if str(r.get("name", "")).strip()
        ]
        cfg.extra_tickets = [
            ExtraTicket(
                key=str(r.get("key", "")).strip(),
                assignee=str(r.get("assignee", "")).strip(),
                notes=str(r.get("notes", "")).strip(),
            )
            for r in self.exticket_table.rows()
            if str(r.get("key", "")).strip()
        ]
        cfg.excluded_tickets = [
            str(r.get("key", "")).strip()
            for r in self.exclticket_table.rows()
            if str(r.get("key", "")).strip()
        ]
        return cfg

    # ── action handlers ─────────────────────────────────────────────────

    def _save_json(self) -> None:
        cfg = self.gather_config()
        if not cfg.sprint_name:
            QMessageBox.warning(self, "Missing name", "Sprint name is required to save.")
            return
        path = configs_dir() / f"{cfg.sprint_name.replace(' ', '_')}.json"
        config_io.save_json(cfg, path)
        QMessageBox.information(self, "Saved", f"Configuration saved to:\n{path}")

    def _import_md(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import sprint_report_config.md", "", "Markdown (*.md);;All files (*)",
        )
        if not path:
            return
        try:
            cfg = config_io.load_markdown(Path(path))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        self.set_config(cfg)
        QMessageBox.information(self, "Imported", f"Loaded config from:\n{path}")

    def _export_md(self) -> None:
        cfg = self.gather_config()
        default_name = f"sprint_report_config_{cfg.sprint_name.replace(' ', '_')}.md"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export sprint_report_config.md", default_name, "Markdown (*.md)",
        )
        if not path:
            return
        try:
            config_io.save_markdown(cfg, Path(path))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Exported", f"Wrote markdown to:\n{path}")

    def _on_next(self) -> None:
        cfg = self.gather_config()
        if not cfg.sprint_name:
            QMessageBox.warning(self, "Missing name", "Sprint name is required.")
            return
        if not self.payload:
            QMessageBox.warning(self, "No sprint data",
                                "Load a sprint from the Sprint tab before generating.")
            return
        # Auto-save
        try:
            config_io.save_json(cfg, configs_dir() / f"{cfg.sprint_name.replace(' ', '_')}.json")
        except Exception:  # noqa: BLE001
            pass
        self.config = cfg
        self.config_ready.emit(cfg)


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0

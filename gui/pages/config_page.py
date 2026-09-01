"""Configure team, leaves, exclusions, extra tickets, report options."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from gui.pack_model import PackSlot, ReportPack
from gui.settings import AppSettings, configs_dir
from gui.widgets.editable_table import Column, EditableTable


class ConfigPage(QWidget):
    """Holds the SprintConfig editor.  Emits ``config_ready`` when the pack is ready."""

    config_ready = Signal()
    back_to_sprint = Signal()

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.config: SprintConfig = SprintConfig()
        self.payload: dict = {}
        self._pack = ReportPack()
        self._active_index = -1
        self._board_id = 0

        title = QLabel("<h2>Sprint configuration</h2>")
        self.subtitle = QLabel("Add a sprint on the Sprint tab to populate this form.")
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet("color: #555;")

        pack_row = QHBoxLayout()
        pack_row.addWidget(QLabel("Editing"))
        self.pack_combo = QComboBox()
        self.pack_combo.setMinimumWidth(320)
        pack_row.addWidget(self.pack_combo, stretch=1)
        self.pack_hint = QLabel("")
        pack_row.addWidget(self.pack_hint)

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
        self.cb_per_ticket.setChecked(True)
        o_form.addRow(self.cb_per_ticket)

        # ── Action row ──
        actions = QHBoxLayout()
        self.back_btn = QPushButton("← Sprint (add more)")
        self.import_btn = QPushButton("Import .md…")
        self.export_btn = QPushButton("Export .md…")
        self.save_btn = QPushButton("Save config")
        self.next_btn = QPushButton("Generate →")
        self.next_btn.setDefault(True)
        actions.addWidget(self.back_btn)
        actions.addWidget(self.import_btn)
        actions.addWidget(self.export_btn)
        actions.addStretch(1)
        actions.addWidget(self.save_btn)
        actions.addWidget(self.next_btn)

        self.back_btn.clicked.connect(self._on_back)
        self.import_btn.clicked.connect(self._import_md)
        self.export_btn.clicked.connect(self._export_md)
        self.save_btn.clicked.connect(self._save_json)
        self.next_btn.clicked.connect(self._on_next)
        self.pack_combo.currentIndexChanged.connect(self._on_pack_member_changed)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.subtitle)
        layout.addLayout(pack_row)
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
        # Combo delegates call combo_options_provider() when an editor opens,
        # so there is no need to recreate delegates here (that can crash PySide6).
        pass

    # ── pack binding ────────────────────────────────────────────────────

    def bind_pack(self, pack: ReportPack, active_index: int = 0) -> None:
        """Attach the presenter pack and show the given member."""
        self._pack = pack
        self.pack_combo.blockSignals(True)
        self.pack_combo.clear()
        for slot in pack.slots:
            self.pack_combo.addItem(slot.label)
        self.pack_combo.blockSignals(False)
        n = len(pack)
        self.pack_hint.setText(f"{n} sprint{'s' if n != 1 else ''} in pack")
        self.pack_combo.setEnabled(n > 1)
        if n == 0:
            self._active_index = -1
            self.subtitle.setText("Add a sprint on the Sprint tab to populate this form.")
            return
        idx = max(0, min(active_index, n - 1))
        self._active_index = -1  # force load
        self.pack_combo.setCurrentIndex(idx)
        self._load_slot(idx, flush_current=False)

    def flush_active(self) -> None:
        """Write the current form into the active pack slot."""
        if self._active_index < 0 or self._active_index >= len(self._pack):
            return
        cfg = self.gather_config()
        slot = self._pack.slots[self._active_index]
        slot.config = cfg
        slot.payload = self.payload
        self.config = cfg
        try:
            if cfg.sprint_name:
                config_io.save_json(
                    cfg, configs_dir() / f"{cfg.sprint_name.replace(' ', '_')}.json"
                )
            self._persist_board_roster(cfg)
        except Exception:  # noqa: BLE001
            log.debug("flush_active save failed", exc_info=True)

    def build_config_from_payload(
        self, payload: dict, sprint: dict, board_id: int
    ) -> SprintConfig:
        """Build config for one sprint.

        Team = sprint assignees + planned-leave names (no cross-sprint merge).
        Saved JSON supplies sprint settings and role/include hints for those
        names; stale extra names in an old save file are ignored on load.
        """
        cfg = SprintConfig()
        cfg.sprint_name = sprint.get("name", "")
        try:
            sd = date.fromisoformat((sprint.get("startDate") or "")[:10])
            ed = date.fromisoformat((sprint.get("endDate") or "")[:10])
            weeks = max(1, round((ed - sd).days / 7))
            cfg.sprint_duration_weeks = int(weeks)
        except Exception:
            cfg.sprint_duration_weeks = 2

        saved: SprintConfig | None = None
        saved_path = configs_dir() / f"{cfg.sprint_name.replace(' ', '_')}.json"
        if saved_path.exists():
            try:
                saved = config_io.load_json(saved_path)
            except Exception:  # noqa: BLE001
                saved = None

        if saved is not None:
            # Keep sprint-level settings from the last save of this sprint.
            cfg = saved

        assignees = jira_service.assignees_in_payload(payload)
        leave_names = {
            (entry.name or "").strip()
            for entry in (cfg.planned_leaves or [])
            if (entry.name or "").strip()
        }
        preserved = {m.name: m for m in (saved.team_members if saved else [])}
        roster = config_io.load_board_roster(configs_dir(), board_id)
        hints = {m.name: m for m in roster}

        def member_for(name: str) -> TeamMember:
            if name in preserved:
                return preserved[name]
            if name in hints:
                h = hints[name]
                return TeamMember(
                    name=name, role=h.role or "Developer", included=bool(h.included)
                )
            return TeamMember(name=name, role="Developer", included=True)

        team: list[TeamMember] = []
        seen: set[str] = set()
        for name in assignees:
            team.append(member_for(name))
            seen.add(name)
        for name in sorted(leave_names):
            if name in seen:
                continue
            team.append(member_for(name))
            seen.add(name)

        dropped = len(preserved) - len({m.name for m in team} & set(preserved))
        cfg.team_members = team
        log.info(
            "build_config_from_payload %s: %d assignees + %d leave-only → %d team "
            "(%d stale names ignored from saved config)",
            cfg.sprint_name,
            len(assignees),
            len(leave_names - set(assignees)),
            len(team),
            max(0, dropped),
        )
        return cfg

    def _reconcile_slot_config(self, slot: PackSlot) -> SprintConfig:
        """Rebuild team from this slot's payload; keep other fields from session config."""
        fresh = self.build_config_from_payload(slot.payload, slot.sprint, slot.board_id)

        prev = slot.config
        if prev is None:
            slot.config = fresh
            return fresh

        # Preserve in-session edits for non-team fields.
        fresh.planned_leaves = prev.planned_leaves
        fresh.other_exclusions = prev.other_exclusions
        fresh.extra_tickets = prev.extra_tickets
        fresh.excluded_tickets = prev.excluded_tickets
        fresh.meeting_days_reserved = prev.meeting_days_reserved
        fresh.report_date = prev.report_date
        fresh.show_per_ticket_details = prev.show_per_ticket_details
        if prev.sprint_duration_weeks:
            fresh.sprint_duration_weeks = prev.sprint_duration_weeks
        if prev.sprint_name:
            fresh.sprint_name = prev.sprint_name

        leave_names = {
            (entry.name or "").strip()
            for entry in (fresh.planned_leaves or [])
            if (entry.name or "").strip()
        }
        prev_by = {m.name: m for m in prev.team_members}
        by_name = {m.name: m for m in fresh.team_members}
        for name in leave_names:
            if name in by_name:
                continue
            old = prev_by.get(name)
            by_name[name] = old or TeamMember(
                name=name, role="Developer", included=True
            )
        # Keep everyone the user added or edited this session (incl. no-ticket).
        for old in prev.team_members:
            if old.name in by_name:
                by_name[old.name] = TeamMember(
                    name=old.name, role=old.role, included=old.included
                )
            else:
                by_name[old.name] = old

        order = list(jira_service.assignees_in_payload(slot.payload))
        for name in leave_names:
            if name not in order:
                order.append(name)
        for old in prev.team_members:
            if old.name not in order:
                order.append(old.name)
        for name in sorted(by_name):
            if name not in order:
                order.append(name)
        fresh.team_members = [by_name[n] for n in order if n in by_name]
        slot.config = fresh
        return fresh

    def ensure_slot_config(self, slot: PackSlot) -> SprintConfig:
        """Return slot.config with team list reconciled to this sprint's payload."""
        return self._reconcile_slot_config(slot)

    def _on_pack_member_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._pack):
            return
        if index == self._active_index:
            return
        self._load_slot(index, flush_current=True)

    def _load_slot(self, index: int, *, flush_current: bool) -> None:
        if flush_current and self._active_index >= 0:
            self.flush_active()
        if index < 0 or index >= len(self._pack):
            return
        slot = self._pack.slots[index]
        self._active_index = index
        self._board_id = slot.board_id
        self.payload = slot.payload
        self._last_sprint_meta = slot.sprint
        sprint = slot.sprint
        self.subtitle.setText(
            f"Editing: <b>{slot.label}</b> "
            f"({(sprint.get('startDate') or '')[:10]} → {(sprint.get('endDate') or '')[:10]}) — "
            f"{len(slot.payload.get('issues', []))} issues."
        )
        cfg = self.ensure_slot_config(slot)
        self.set_config(cfg)

    def _on_back(self) -> None:
        self.flush_active()
        self.back_to_sprint.emit()

    # ── public entry: populate UI from a payload ─────────────────────────

    def populate_from_payload(
        self, payload: dict, sprint: dict, board_id: int | None = None
    ) -> None:
        """Legacy single-sprint populate (also used when seeding a slot)."""
        log.info("ConfigPage.populate_from_payload: sprint=%s", sprint.get("name"))
        bid = int(
            board_id
            if board_id is not None
            else getattr(self.settings, "last_board_id", 0) or 0
        )
        self._board_id = bid
        self.payload = payload
        self._last_sprint_meta = sprint
        self.subtitle.setText(
            f"Sprint loaded: <b>{sprint.get('name', '')}</b> "
            f"({(sprint.get('startDate') or '')[:10]} → {(sprint.get('endDate') or '')[:10]}) — "
            f"{len(payload.get('issues', []))} issues."
        )
        cfg = self.build_config_from_payload(payload, sprint, bid)
        self.set_config(cfg)

    def set_config(self, cfg: SprintConfig) -> None:
        log.info("ConfigPage.set_config: %d members, %d leaves, %d exclusions",
                 len(cfg.team_members), len(cfg.planned_leaves), len(cfg.other_exclusions))
        self.config = cfg

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

    def gather_config(self) -> SprintConfig:
        cfg = SprintConfig()
        cfg.sprint_name = self.name_edit.text().strip()
        cfg.sprint_duration_weeks = int(self.duration_spin.value())
        cfg.meeting_days_reserved = float(self.meeting_spin.value())
        d = self.report_date.date()
        cfg.report_date = d.toString("yyyy-MM-dd") if d.isValid() else ""
        cfg.show_per_ticket_details = self.cb_per_ticket.isChecked()

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
        board_id = self._board_id or int(getattr(self.settings, "last_board_id", 0) or 0)
        config_io.save_board_roster(configs_dir(), board_id, cfg.team_members)
        if 0 <= self._active_index < len(self._pack):
            self._pack.slots[self._active_index].config = cfg
        QMessageBox.information(self, "Saved", f"Configuration saved to:\n{path}")

    def _persist_board_roster(self, cfg: SprintConfig | None = None) -> None:
        """Update the board roster so future sprints keep people with no tickets."""
        cfg = cfg or self.gather_config()
        board_id = self._board_id or int(getattr(self.settings, "last_board_id", 0) or 0)
        if board_id and cfg.team_members:
            config_io.save_board_roster(configs_dir(), board_id, cfg.team_members)

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
        if len(self._pack) == 0:
            QMessageBox.warning(
                self,
                "Empty pack",
                "Add at least one sprint on the Sprint tab before generating.",
            )
            return
        self.flush_active()
        for i, slot in enumerate(self._pack.slots):
            self.ensure_slot_config(slot)
            if not slot.config or not slot.config.sprint_name:
                QMessageBox.warning(
                    self,
                    "Missing name",
                    f"Sprint name is required for pack member {i + 1}: {slot.label}",
                )
                self.bind_pack(self._pack, active_index=i)
                return
            if not slot.payload:
                QMessageBox.warning(
                    self,
                    "No sprint data",
                    f"Missing Jira data for {slot.label}. Re-add it on the Sprint tab.",
                )
                return
            try:
                cfg = slot.config
                config_io.save_json(
                    cfg, configs_dir() / f"{cfg.sprint_name.replace(' ', '_')}.json"
                )
                if slot.board_id and cfg.team_members:
                    config_io.save_board_roster(
                        configs_dir(), slot.board_id, cfg.team_members
                    )
            except Exception:  # noqa: BLE001
                pass
        self.config = self._pack.slots[self._active_index].config
        self.payload = self._pack.slots[self._active_index].payload
        self.config_ready.emit()


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0

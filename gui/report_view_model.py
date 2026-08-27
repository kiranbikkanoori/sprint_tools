"""Structured report view-model for the native Generate UI tabs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from config_parser import SprintConfig
from report_generator import (
    SprintWorkReport,
    _log_window_end,
    _remaining_hours_by_assignee,
    build_backlog_churn_rows,
    build_capacity_hours_by_person,
    build_completion_velocity,
    build_effective_days_by_person,
    build_kpi_summary,
    build_ticket_rows,
)
from utils import working_dates_in_range


@dataclass
class OverviewChip:
    label: str
    value: str
    detail: str = ""  # secondary line, e.g. "6/8" under a percent


@dataclass
class KpiViewRow:
    label: str
    value: str
    notes: str


@dataclass
class CompletionTeamMetric:
    metric: str
    value: str
    target: str
    emphasize: bool = False


@dataclass
class CompletionPersonRow:
    name: str
    tickets_frac: str
    ticket_pct: str
    sp_frac: str
    sp_pct: str
    velocity: str


@dataclass
class FixUpRow:
    severity: str  # High | Med | Low
    type_label: str
    key: str
    person: str
    summary: str
    action: str


@dataclass
class DayCell:
    story: float
    task: float
    subtask: float

    @property
    def total(self) -> float:
        return self.story + self.task + self.subtask


@dataclass
class HoursPersonRow:
    name: str
    days: dict[date, DayCell] = field(default_factory=dict)
    logged: float = 0.0
    remaining: float = 0.0
    capacity: float = 0.0
    # date -> bucket -> key -> hours (for drawer)
    ticket_detail: dict[date, dict[str, dict[str, float]]] = field(default_factory=dict)


@dataclass
class TicketViewRow:
    key: str
    summary: str
    type_: str
    assignee: str
    status: str
    estimate_hours: float
    remaining_hours: float | None
    story_points: float
    is_done: bool
    has_warn: bool


@dataclass
class ReportViewModel:
    sprint_name: str
    sprint_goal: str
    display_dates: list[date]
    chips: list[OverviewChip]
    fixup_count: int
    fixups: list[FixUpRow]
    hours_rows: list[HoursPersonRow]
    tickets: list[TicketViewRow]
    kpi_rows: list[KpiViewRow]
    completion_team: list[CompletionTeamMetric]
    completion_people: list[CompletionPersonRow]
    default_tab: str  # "fixups" | "overview"


def _pct(p: float | None) -> str:
    return "—" if p is None else f"{int(round(p))}%"


def _vel(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f}"


def _sp(v: float) -> str:
    """Compact story-point / day display (drop trailing .0)."""
    if abs(v - round(v)) < 1e-6:
        return str(int(round(v)))
    return f"{v:.1f}"


def build_report_view_model(
    config: SprintConfig,
    payload: dict,
    work_report: SprintWorkReport,
) -> ReportViewModel:
    sprint_info = payload.get("sprint") or {}
    sprint_start = date.fromisoformat(sprint_info["start_date"])
    sprint_end = date.fromisoformat(sprint_info["end_date"])
    sprint_goal = (sprint_info.get("goal") or "").strip()
    report_date = (
        date.fromisoformat(config.report_date) if config.report_date else date.today()
    )
    issues = payload.get("issues") or []
    sprint_start_raw = sprint_info.get("start_datetime") or sprint_info.get("start_date")

    all_dates = working_dates_in_range(sprint_start, sprint_end)
    report_cap = _log_window_end(sprint_end, report_date)
    display_dates = [d for d in all_dates if d <= report_cap]

    effective = build_effective_days_by_person(config, work_report)
    team_completion = build_completion_velocity(config, issues, effective)
    ticket_rows = build_ticket_rows(config, issues)
    churn_rows = build_backlog_churn_rows(config, issues, sprint_start_raw)
    capacity = build_capacity_hours_by_person(config, work_report)
    rem_story = _remaining_hours_by_assignee(config, issues, bucket="story")
    rem_task = _remaining_hours_by_assignee(config, issues, bucket="task")

    open_count = sum(1 for r in ticket_rows if not r.is_effectively_done)
    committed = team_completion.tickets_committed
    team_remaining = sum(rem_story.get(n, 0.0) + rem_task.get(n, 0.0) for n in work_report.included_names)
    team_capacity = sum(capacity.get(n, 0.0) for n in work_report.included_names)

    # Primary value + supporting detail (pct + fraction, etc.)
    chips = [
        OverviewChip(
            "Completion (tickets)",
            _pct(team_completion.ticket_pct),
            f"{team_completion.tickets_done}/{team_completion.tickets_committed}",
        ),
        OverviewChip(
            "Completion (SP)",
            _pct(team_completion.sp_pct),
            f"{_sp(team_completion.sp_delivered)}/{_sp(team_completion.sp_committed)}",
        ),
        OverviewChip(
            "Velocity",
            f"{_vel(team_completion.velocity)} SP/day",
            f"{_sp(team_completion.sp_delivered)} SP ÷ {_sp(team_completion.effective_days)}d",
        ),
        OverviewChip(
            "Open tickets",
            str(open_count),
            f"{open_count} open · {committed} committed",
        ),
        OverviewChip(
            "Churn",
            str(len(churn_rows)),
            f"{len(churn_rows)} added after start",
        ),
        OverviewChip(
            "Team remaining",
            f"{team_remaining:.1f}h",
            f"of {team_capacity:.1f}h capacity",
        ),
        OverviewChip(
            "Team capacity",
            f"{team_capacity:.1f}h",
            f"{team_remaining:.1f}h still remaining",
        ),
    ]

    # ── Fix-ups ─────────────────────────────────────────────────────────
    fixups: list[FixUpRow] = []
    for row in churn_rows:
        done = False
        for t in ticket_rows:
            if t.key == row.key:
                done = t.is_effectively_done
                break
        sev = "Low" if done else "High"
        fixups.append(
            FixUpRow(
                severity=sev,
                type_label="Churn",
                key=row.key,
                person=row.assignee,
                summary=row.summary[:80],
                action="Added after sprint start — confirm scope with the team.",
            )
        )

    for r in ticket_rows:
        if r.is_effectively_done and r.remaining_hours is not None and r.remaining_hours > 1e-6:
            fixups.append(
                FixUpRow(
                    severity="Med",
                    type_label="⚠ Remaining",
                    key=r.key,
                    person=r.assignee,
                    summary=r.summary[:80],
                action="Done/Resolved but remaining > 0 — clear remaining or reopen.",
            )
        )

    for e in work_report.errors_child_remaining:
        fixups.append(
            FixUpRow(
                severity="Med",
                type_label="Sub-task remaining",
                key=e.key,
                person=e.assignee,
                summary=e.summary[:80],
                action=f"Sub-task still has {e.remaining_hours:.1f}h remaining"
                + (f" (parent {e.parent_key})." if e.parent_key else "."),
            )
        )

    for e in work_report.errors_child_worklogs:
        authors = ", ".join(e.hours_by_author.keys()) or e.assignee
        fixups.append(
            FixUpRow(
                severity="Med",
                type_label="Sub-task worklog",
                key=e.key,
                person=authors,
                summary=e.summary[:80],
                action=f"{e.total_hours:.1f}h logged on sub-task — move logs to story/task.",
            )
        )

    sev_order = {"High": 0, "Med": 1, "Low": 2}
    fixups.sort(key=lambda f: (sev_order.get(f.severity, 9), f.type_label, f.key))

    # ── Hours combined ──────────────────────────────────────────────────
    hours_rows: list[HoursPersonRow] = []
    for name in work_report.included_names:
        pdata = work_report.daily_story_task.get(name, {})
        tdetail = work_report.daily_ticket_hours.get(name, {})
        days: dict[date, DayCell] = {}
        logged = 0.0
        for d in display_dates:
            cell = pdata.get(d, {})
            dc = DayCell(
                story=float(cell.get("story", 0.0)),
                task=float(cell.get("task", 0.0)),
                subtask=float(cell.get("subtask", 0.0)),
            )
            days[d] = dc
            logged += dc.story + dc.task  # capacity compare uses allowed logs
        rem = float(rem_story.get(name, 0.0) + rem_task.get(name, 0.0))
        hours_rows.append(
            HoursPersonRow(
                name=name,
                days=days,
                logged=logged,
                remaining=rem,
                capacity=float(capacity.get(name, 0.0)),
                ticket_detail={
                    d: {
                        "story": dict(tdetail.get(d, {}).get("story", {})),
                        "task": dict(tdetail.get(d, {}).get("task", {})),
                        "subtask": dict(tdetail.get(d, {}).get("subtask", {})),
                    }
                    for d in display_dates
                },
            )
        )

    tickets = [
        TicketViewRow(
            key=r.key,
            summary=r.summary,
            type_=r.type_,
            assignee=r.assignee,
            status=r.status,
            estimate_hours=r.estimate_hours,
            remaining_hours=r.remaining_hours,
            story_points=r.story_points,
            is_done=r.is_effectively_done,
            has_warn=(
                r.is_effectively_done
                and r.remaining_hours is not None
                and r.remaining_hours > 1e-6
            ),
        )
        for r in ticket_rows
    ]

    # ── KPIs + Completion & Velocity (same tables as MD/HTML export) ──
    kpi_rows = [
        KpiViewRow(label=r.label, value=r.value, notes=r.notes)
        for r in build_kpi_summary(config, issues, team_completion)
    ]
    tc = team_completion
    completion_team = [
        CompletionTeamMetric("Tickets committed", str(tc.tickets_committed), "—"),
        CompletionTeamMetric("Tickets done", str(tc.tickets_done), "—"),
        CompletionTeamMetric(
            "Completion rate (tickets)", _pct(tc.ticket_pct), "≥ 90%", emphasize=True
        ),
        CompletionTeamMetric("Story points committed", _sp(tc.sp_committed), "—"),
        CompletionTeamMetric("Story points delivered", _sp(tc.sp_delivered), "—"),
        CompletionTeamMetric(
            "Completion rate (story points)", _pct(tc.sp_pct), "≥ 90%", emphasize=True
        ),
        CompletionTeamMetric("Effective person-days (team)", _sp(tc.effective_days), "—"),
        CompletionTeamMetric(
            "Velocity (SP / person-day)", _vel(tc.velocity), "—", emphasize=True
        ),
    ]
    completion_people = [
        CompletionPersonRow(
            name=r.name,
            tickets_frac=f"{r.tickets_done} / {r.tickets_committed}",
            ticket_pct=_pct(r.ticket_pct),
            sp_frac=f"{_sp(r.sp_delivered)} / {_sp(r.sp_committed)}",
            sp_pct=_pct(r.sp_pct),
            velocity=_vel(r.velocity),
        )
        for r in tc.rows
    ]

    return ReportViewModel(
        sprint_name=config.sprint_name or sprint_info.get("name", ""),
        sprint_goal=sprint_goal,
        display_dates=display_dates,
        chips=chips,
        fixup_count=len(fixups),
        fixups=fixups,
        hours_rows=hours_rows,
        tickets=tickets,
        kpi_rows=kpi_rows,
        completion_team=completion_team,
        completion_people=completion_people,
        default_tab="fixups" if fixups else "overview",
    )

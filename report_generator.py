"""
Text report generator — story vs task worklogging model.

Logged hours for reporting come from **Story** and **Task** Jira issue types (by worklog
author). **Sub-task** worklogs and non-zero remaining on sub-tasks are validation errors.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from config_parser import SprintConfig
from utils import (
    effective_issue_type,
    format_jira_datetime_ist,
    hours_to_jira,
    parse_jira_time_to_hours,
    worklog_started_date,
    working_dates_in_range,
)


@dataclass
class ChildRemainingError:
    key: str
    summary: str
    assignee: str
    parent_key: str | None
    remaining_hours: float


@dataclass
class ChildWorklogError:
    key: str
    summary: str
    assignee: str
    parent_key: str | None
    hours_by_author: dict[str, float]
    total_hours: float


@dataclass
class SprintWorkReport:
    """Per-person story vs task hours per calendar day (sprint window)."""

    included_names: list[str]
    # person -> date -> {"story": h, "task": h}
    daily_story_task: dict[str, dict[date, dict[str, float]]] = field(default_factory=dict)
    # person -> date -> "story" | "task" -> issue_key -> hours (same window as daily_story_task)
    daily_ticket_hours: dict[str, dict[date, dict[str, dict[str, float]]]] = field(
        default_factory=dict
    )
    errors_child_remaining: list[ChildRemainingError] = field(default_factory=list)
    errors_child_worklogs: list[ChildWorklogError] = field(default_factory=list)


@dataclass
class TicketRow:
    """One row in the Sprint Tickets — Status & Remaining Work table."""

    key: str
    summary: str
    type_: str  # "Story" | "Task"
    assignee: str
    status: str
    status_category: str
    estimate_hours: float
    remaining_hours: float | None
    story_points: float
    is_effectively_done: bool


@dataclass
class PersonCompletion:
    """Per-person completion / velocity row."""

    name: str
    tickets_committed: int
    tickets_done: int
    sp_committed: float
    sp_delivered: float
    effective_days: float

    @property
    def ticket_pct(self) -> float | None:
        if self.tickets_committed == 0:
            return None
        return self.tickets_done / self.tickets_committed * 100.0

    @property
    def sp_pct(self) -> float | None:
        if self.sp_committed <= 1e-6:
            return None
        return self.sp_delivered / self.sp_committed * 100.0

    @property
    def velocity(self) -> float | None:
        if self.effective_days <= 1e-6:
            return None
        return self.sp_delivered / self.effective_days


@dataclass
class TeamCompletion:
    """Team-level completion / velocity totals plus per-person rows."""

    tickets_committed: int
    tickets_done: int
    sp_committed: float
    sp_delivered: float
    effective_days: float
    rows: list[PersonCompletion] = field(default_factory=list)

    @property
    def ticket_pct(self) -> float | None:
        if self.tickets_committed == 0:
            return None
        return self.tickets_done / self.tickets_committed * 100.0

    @property
    def sp_pct(self) -> float | None:
        if self.sp_committed <= 1e-6:
            return None
        return self.sp_delivered / self.sp_committed * 100.0

    @property
    def velocity(self) -> float | None:
        if self.effective_days <= 1e-6:
            return None
        return self.sp_delivered / self.effective_days


@dataclass
class KpiSummaryRow:
    label: str
    value: str
    notes: str


@dataclass
class BacklogChurnRow:
    key: str
    summary: str
    assignee: str
    status: str
    sprint_started_ist: str
    added_to_sprint_ist: str


def _log_window_end(sprint_end: date, report_date: date | None) -> date:
    if report_date is None:
        return sprint_end
    return min(sprint_end, report_date)


def _issue_remaining_hours(issue: dict) -> float:
    rem = issue.get("remaining_estimate_hours")
    if rem is not None and rem >= 0:
        return float(rem)
    raw = issue.get("remaining_estimate_raw")
    if raw:
        return parse_jira_time_to_hours(str(raw))
    return 0.0


def build_sprint_work_report(
    config: SprintConfig,
    sprint_start: date,
    sprint_end: date,
    issues: list[dict],
    worklogs: dict[str, list[dict]],
    report_date: date | None = None,
) -> SprintWorkReport:
    """
    Build daily story/task hours for included members, and sub-task validation errors.

    Worklogs counted for the daily matrix use dates in [sprint_start, log_end] inclusive,
    where log_end = min(sprint_end, report_date or sprint_end).

    Sub-task worklog errors use the same date window. Only included authors count toward
    story/task totals; sub-task error lists include all authors.
    """
    excluded = set(config.excluded_tickets)
    included = [m.name for m in config.team_members if m.included]
    included_set = set(included)
    log_end = _log_window_end(sprint_end, report_date)

    daily: dict[str, dict[date, dict[str, float]]] = {
        name: defaultdict(lambda: {"story": 0.0, "task": 0.0}) for name in included
    }
    detail: dict[str, dict[date, dict[str, dict[str, float]]]] = {
        name: defaultdict(
            lambda: {"story": defaultdict(float), "task": defaultdict(float)}
        )
        for name in included
    }

    errors_remaining: list[ChildRemainingError] = []
    child_wl_accum: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    child_wl_meta: dict[str, dict] = {}

    for issue in issues:
        key = issue["key"]
        if key in excluded:
            continue
        itype = effective_issue_type(issue)
        rem = _issue_remaining_hours(issue)

        if itype == "Sub-task" and rem > 1e-6:
            errors_remaining.append(
                ChildRemainingError(
                    key=key,
                    summary=(issue.get("summary") or "")[:80],
                    assignee=issue.get("assignee") or "Unassigned",
                    parent_key=(issue.get("parent_key")),
                    remaining_hours=rem,
                )
            )

        wl_list = worklogs.get(key, [])
        if itype == "Sub-task":
            child_wl_meta[key] = issue
            for wl in wl_list:
                wl_date = worklog_started_date(wl)
                if wl_date is None:
                    continue
                if not (sprint_start <= wl_date <= log_end):
                    continue
                author = wl["author"]
                hrs = wl["seconds"] / 3600.0
                child_wl_accum[key][author] += hrs
            continue

        if itype not in ("Story", "Task"):
            continue

        bucket = "story" if itype == "Story" else "task"
        for wl in wl_list:
            wl_date = worklog_started_date(wl)
            if wl_date is None:
                continue
            if not (sprint_start <= wl_date <= log_end):
                continue
            author = wl["author"]
            if author not in included_set:
                continue
            hrs = wl["seconds"] / 3600.0
            daily[author][wl_date][bucket] += hrs
            detail[author][wl_date][bucket][key] += hrs

    errors_wl: list[ChildWorklogError] = []
    for ckey, by_author in child_wl_accum.items():
        total = sum(by_author.values())
        if total <= 1e-6:
            continue
        meta = child_wl_meta.get(ckey, {})
        errors_wl.append(
            ChildWorklogError(
                key=ckey,
                summary=(meta.get("summary") or "")[:80],
                assignee=meta.get("assignee") or "Unassigned",
                parent_key=meta.get("parent_key"),
                hours_by_author=dict(sorted(by_author.items(), key=lambda x: -x[1])),
                total_hours=total,
            )
        )
    errors_wl.sort(key=lambda e: e.key)

    # Normalize inner dicts from defaultdict to plain dict for iteration
    daily_out: dict[str, dict[date, dict[str, float]]] = {}
    detail_out: dict[str, dict[date, dict[str, dict[str, float]]]] = {}
    for name in included:
        daily_out[name] = {
            d: {"story": v["story"], "task": v["task"]}
            for d, v in sorted(daily[name].items())
        }
        detail_out[name] = {}
        for d, buckets in sorted(detail[name].items()):
            detail_out[name][d] = {
                "story": dict(buckets["story"]),
                "task": dict(buckets["task"]),
            }

    return SprintWorkReport(
        included_names=included,
        daily_story_task=daily_out,
        daily_ticket_hours=detail_out,
        errors_child_remaining=sorted(errors_remaining, key=lambda e: e.key),
        errors_child_worklogs=errors_wl,
    )


def build_effective_days_by_person(
    config: SprintConfig,
    work_report: SprintWorkReport,
) -> dict[str, float]:
    """
    Build effective person-days for included members.

    This keeps the velocity denominator aligned with the previous capacity model:
    effective days = sprint weeks × 5 − meeting reserve − planned leaves.
    """
    work_days = float(config.sprint_duration_weeks) * 5.0
    meeting_days = float(config.meeting_days_reserved)

    leaves_by_name: dict[str, float] = defaultdict(float)
    for entry in config.planned_leaves:
        leaves_by_name[entry.name] += float(entry.days)

    out: dict[str, float] = {}
    for name in work_report.included_names:
        leave_d = leaves_by_name.get(name, 0.0)
        eff_d = max(0.0, work_days - meeting_days - leave_d)
        out[name] = eff_d
    return out


def _fmt_d(x: float) -> str:
    """Format a day-count: integer when whole, else one decimal."""
    if abs(x - round(x)) < 1e-6:
        return str(int(round(x)))
    return f"{x:.1f}"


def _fmt_sp(v: float) -> str:
    """Format a story-point value: integer when whole, else :g."""
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:g}"


def build_ticket_rows(
    config: SprintConfig,
    issues: list[dict],
) -> list[TicketRow]:
    """
    Build one row per **Story / Task** in the sprint (after dropping
    ``excluded_tickets``), sorted **unfinished-first** then by status, then by key.

    Tickets whose `status` is `Resolved` are treated as **effectively done** and
    sorted with `Closed`, even though Jira reports their `status_category` as
    `In Progress`. (Many Jira workflows keep a final `Resolved` state.)
    """
    excluded = set(config.excluded_tickets)
    rows: list[TicketRow] = []
    for issue in issues:
        if issue.get("key") in excluded:
            continue
        itype = effective_issue_type(issue)
        if itype not in ("Story", "Task"):
            continue
        sc = (issue.get("status_category") or "").strip()
        st = (issue.get("status") or "").strip()
        is_done = sc.lower() in ("done", "complete") or st.lower() == "resolved"

        rem = _issue_remaining_hours(issue)
        # Distinguish "no remaining estimate at all" (None) from "explicitly 0":
        # _issue_remaining_hours returns 0.0 for both, so re-check the raw fields.
        if (
            issue.get("remaining_estimate_hours") is None
            and not issue.get("remaining_estimate_raw")
        ):
            rem_val: float | None = None
        else:
            rem_val = float(rem)

        try:
            est_val = float(issue.get("estimate_hours") or 0.0)
        except (TypeError, ValueError):
            est_val = 0.0
        try:
            sp_val = float(issue.get("story_points") or 0.0)
        except (TypeError, ValueError):
            sp_val = 0.0

        rows.append(
            TicketRow(
                key=issue.get("key", ""),
                summary=(issue.get("summary") or "").strip(),
                type_=itype,
                assignee=(issue.get("assignee") or "Unassigned").strip(),
                status=st,
                status_category=sc,
                estimate_hours=est_val,
                remaining_hours=rem_val,
                story_points=sp_val,
                is_effectively_done=is_done,
            )
        )

    rows.sort(key=lambda r: (r.is_effectively_done, r.status, r.key))
    return rows


def build_completion_velocity(
    config: SprintConfig,
    issues: list[dict],
    effective_days_by_name: dict[str, float],
) -> TeamCompletion:
    """
    Compute Sprint Completion Rate (tickets + story points) and team Velocity.

    "Done" is detected from ``status_category`` matching ``Done`` / ``Complete``
    (Jira's canonical status category for closed work). Sub-tasks and
    ``excluded_tickets`` are dropped, matching the rest of the report. Per-person
    rows are produced only for **included** team members; unassigned tickets
    contribute to team totals only.
    """
    excluded = set(config.excluded_tickets)
    included = list(effective_days_by_name)
    per_person: dict[str, dict] = {
        n: {"committed": 0, "done": 0, "sp_c": 0.0, "sp_d": 0.0} for n in included
    }

    t_committed = 0
    t_done = 0
    sp_committed = 0.0
    sp_delivered = 0.0

    for issue in issues:
        if issue.get("key") in excluded:
            continue
        if effective_issue_type(issue) not in ("Story", "Task"):
            continue
        sc = (issue.get("status_category") or "").strip().lower()
        st = (issue.get("status") or "").strip().lower()
        # Match the Sprint Tickets table: Resolved is treated as effectively done
        # even though its status_category is still "In Progress" in Jira.
        is_done = sc in ("done", "complete") or st == "resolved"
        sp_raw = issue.get("story_points")
        try:
            sp_val = float(sp_raw) if sp_raw is not None else 0.0
        except (TypeError, ValueError):
            sp_val = 0.0

        t_committed += 1
        sp_committed += sp_val
        if is_done:
            t_done += 1
            sp_delivered += sp_val

        assignee = (issue.get("assignee") or "").strip()
        if assignee in per_person:
            per_person[assignee]["committed"] += 1
            per_person[assignee]["sp_c"] += sp_val
            if is_done:
                per_person[assignee]["done"] += 1
                per_person[assignee]["sp_d"] += sp_val

    rows = [
        PersonCompletion(
            name=n,
            tickets_committed=per_person[n]["committed"],
            tickets_done=per_person[n]["done"],
            sp_committed=per_person[n]["sp_c"],
            sp_delivered=per_person[n]["sp_d"],
            effective_days=effective_days_by_name.get(n, 0.0),
        )
        for n in included
    ]

    return TeamCompletion(
        tickets_committed=t_committed,
        tickets_done=t_done,
        sp_committed=sp_committed,
        sp_delivered=sp_delivered,
        effective_days=sum(effective_days_by_name.values()),
        rows=rows,
    )


def build_kpi_summary(
    config: SprintConfig,
    issues: list[dict],
    team_completion: TeamCompletion,
) -> list[KpiSummaryRow]:
    excluded = set(config.excluded_tickets)

    backlog_churn_available = any("added_after_sprint_start" in i for i in issues)
    backlog_churn_count = 0
    if backlog_churn_available:
        for issue in issues:
            if issue.get("key") in excluded:
                continue
            if effective_issue_type(issue) not in ("Story", "Task"):
                continue
            if bool(issue.get("added_after_sprint_start")):
                backlog_churn_count += 1

    def _pct(p: float | None) -> str:
        return "N/A" if p is None else f"{int(round(p))}%"

    def _vel(v: float | None) -> str:
        return "N/A" if v is None else f"{v:.2f}"

    rows = [
        KpiSummaryRow(
            "Sprint completion rate",
            _pct(team_completion.ticket_pct),
            "Completed tickets / accepted tickets (Stories + Tasks only)",
        ),
        KpiSummaryRow("Participation rate", "N/A", "Not implemented"),
        KpiSummaryRow("Ceremony effectiveness", "N/A", "Not implemented"),
        KpiSummaryRow("Time-box adherence", "N/A", "Not implemented"),
        KpiSummaryRow("Jira hygiene score", "N/A", "Not implemented"),
        KpiSummaryRow(
            "Sprint velocity",
            _vel(team_completion.velocity),
            "Completed story points / effective man-days",
        ),
        KpiSummaryRow("Repetition of similar issue", "N/A", "Not implemented"),
        KpiSummaryRow(
            "Scope stability & backlog churn",
            str(backlog_churn_count) if backlog_churn_available else "N/A",
            "Tickets added after sprint start",
        ),
        KpiSummaryRow(
            "Number of tickets",
            str(team_completion.tickets_committed),
            "Stories + Tasks only",
        ),
        KpiSummaryRow(
            "Number of completed tickets",
            str(team_completion.tickets_done),
            "Stories + Tasks done",
        ),
        KpiSummaryRow(
            "Number of differed tickets",
            str(team_completion.tickets_committed - team_completion.tickets_done),
            "Accepted minus completed",
        ),
    ]
    return rows


def build_backlog_churn_rows(
    config: SprintConfig,
    issues: list[dict],
    sprint_start_raw: str | None,
) -> list[BacklogChurnRow]:
    excluded = set(config.excluded_tickets)
    rows: list[BacklogChurnRow] = []
    sprint_started_ist = format_jira_datetime_ist(sprint_start_raw)
    for issue in issues:
        if issue.get("key") in excluded:
            continue
        if effective_issue_type(issue) not in ("Story", "Task"):
            continue
        if not bool(issue.get("added_after_sprint_start")):
            continue
        summary = (issue.get("summary") or "").strip()
        rows.append(
            BacklogChurnRow(
                key=issue.get("key", ""),
                summary=summary,
                assignee=(issue.get("assignee") or "Unassigned").strip(),
                status=(issue.get("status") or "Unknown").strip(),
                sprint_started_ist=sprint_started_ist,
                added_to_sprint_ist=format_jira_datetime_ist(issue.get("added_to_sprint_at")),
            )
        )
    rows.sort(key=lambda r: (r.added_to_sprint_ist, r.key))
    return rows


def _remaining_hours_by_assignee(
    config: SprintConfig,
    issues: list[dict],
    *,
    bucket: str,
) -> dict[str, float]:
    """
    Sum current Jira remaining estimates by assignee for Stories or Tasks.

    ``bucket`` is ``\"story\"`` or ``\"task\"`` (same meaning as the hours tables).
    Excluded tickets and sub-tasks are skipped. Missing/zero remaining counts as 0.
    """
    want = "Story" if bucket == "story" else "Task"
    excluded = set(config.excluded_tickets)
    out: dict[str, float] = defaultdict(float)
    for issue in issues:
        if issue.get("key") in excluded:
            continue
        if effective_issue_type(issue) != want:
            continue
        assignee = (issue.get("assignee") or "").strip()
        if not assignee or assignee == "Unassigned":
            continue
        rem = _issue_remaining_hours(issue)
        if rem > 0:
            out[assignee] += rem
    return out


def _format_day_cell(
    total_h: float,
    ticket_hours: dict[str, float],
    *,
    max_tickets: int = 14,
) -> str:
    """
    One table cell: bold total plus HTML line breaks and a bullet per ticket
    (issue key + hours only). Uses ``<br>`` for multi-line cells.
    """
    if total_h < 1e-6 and not ticket_hours:
        return "0.0"
    lines: list[str] = [f"**{total_h:.1f}**"]
    items = sorted(ticket_hours.items(), key=lambda x: (-x[1], x[0]))
    positive = [(k, h) for k, h in items if h >= 1e-6]
    for idx, (key, hrs) in enumerate(positive):
        if idx >= max_tickets:
            lines.append(f"• *…and {len(positive) - max_tickets} more*")
            break
        lines.append(f"• `{key}` {hrs:.1f}h")
    return "<br>".join(lines)


def generate_text_report(
    config: SprintConfig,
    sprint_start: date,
    sprint_end: date,
    work_report: SprintWorkReport,
    sprint_goal: str = "",
    *,
    issues: list[dict] | None = None,
    sprint_start_raw: str | None = None,
) -> str:
    """
    Return markdown sprint report (story vs task logging model).

    When ``issues`` is provided, the KPI summary plus ticket-based completion
    sections are included. Pass ``None`` to suppress them (kept for backward-compat
    with any older caller that doesn't have the issues list at hand).
    """
    all_dates = working_dates_in_range(sprint_start, sprint_end)
    report_cap = _log_window_end(
        sprint_end,
        date.fromisoformat(config.report_date) if config.report_date else None,
    )
    display_dates = [d for d in all_dates if d <= report_cap]
    lines: list[str] = []

    def ln(s: str = ""):
        lines.append(s)

    ln(f"# Sprint Report: {config.sprint_name}")
    ln()
    ln(
        f"**Sprint Duration:** {sprint_start.strftime('%b %d, %Y')} \u2013 "
        f"{sprint_end.strftime('%b %d, %Y')} ({config.sprint_duration_weeks} weeks)"
    )
    report_label = config.report_date if config.report_date else "today"
    ln(f"**Report Date:** {report_label}")
    if sprint_goal:
        ln(f"**Sprint Goal:** {sprint_goal}")
    ln()
    report_asof_note = (
        "If **Report Date** in the config is empty, **today’s date** is used as the cut-off, "
        "so you can run this **mid-sprint**: only weekdays from sprint start through that date appear, "
        "and only worklogs on those days are counted."
    )
    ln(
        "> **Worklog source:** By **worklog author**, for team members with **Include in Report = Yes**. "
        f"Columns are **weekdays** in **[{sprint_start.isoformat()}, {report_cap.isoformat()}]** "
        f"(inclusive). {report_asof_note} "
        "**Stories** and **non-story tasks** are in **two tables** below. "
        "**Logged** hours come from worklogs; **Remaining (h)** is the sum of each person's "
        "assigned Story/Task **remaining estimates** in Jira (not original estimate). "
        "Each day cell lists **issue keys** and hours under the daily total."
    )
    ln()

    rem_story = _remaining_hours_by_assignee(config, issues or [], bucket="story")
    rem_task = _remaining_hours_by_assignee(config, issues or [], bucket="task")

    def _emit_hours_table(
        title: str,
        bucket: str,
        logged_label: str,
        remaining_by_name: dict[str, float],
    ) -> None:
        ln("---")
        ln(title)
        ln()
        if not display_dates:
            ln("*No working days in range.*")
            ln()
            return
        hdr = "| Person |"
        sep = "|--------|"
        for d in display_dates:
            hdr += f" {d.strftime('%b %d')} (h) |"
            sep += "--------:|"
        hdr += f" **{logged_label}** | **Remaining (h)** |"
        sep += "--------:|--------:|"
        ln(hdr)
        ln(sep)
        col_totals = [0.0] * len(display_dates)
        team_logged = 0.0
        team_remaining = 0.0
        tdetails = work_report.daily_ticket_hours
        for name in work_report.included_names:
            row = f"| {name} |"
            person_tot = 0.0
            pdata = work_report.daily_story_task.get(name, {})
            for j, d in enumerate(display_dates):
                cell = pdata.get(d, {"story": 0.0, "task": 0.0})
                h = cell[bucket]
                col_totals[j] += h
                person_tot += h
                tickets_for_cell = tdetails.get(name, {}).get(d, {}).get(bucket, {})
                cell_html = _format_day_cell(h, tickets_for_cell)
                row += f" {cell_html} |"
            rem_h = float(remaining_by_name.get(name, 0.0))
            team_logged += person_tot
            team_remaining += rem_h
            row += f" **{person_tot:.1f}** | **{rem_h:.1f}** |"
            ln(row)
        total_row = "| **Team total** |"
        for j in range(len(display_dates)):
            total_row += f" **{col_totals[j]:.1f}** |"
        total_row += f" **{team_logged:.1f}** | **{team_remaining:.1f}** |"
        ln(total_row)
        ln()

    _emit_hours_table(
        "## Stories — logged hours & remaining",
        "story",
        "Logged (h)",
        rem_story,
    )
    _emit_hours_table(
        "## Tasks (non-story) — logged hours & remaining",
        "task",
        "Logged (h)",
        rem_task,
    )

    team_completion: TeamCompletion | None = None
    if issues is not None:
        effective_days_by_name = build_effective_days_by_person(config, work_report)
        team_completion = build_completion_velocity(config, issues, effective_days_by_name)
        kpi_rows = build_kpi_summary(config, issues, team_completion)
        churn_rows = build_backlog_churn_rows(config, issues, sprint_start_raw)
        ln("---")
        ln("## Sprint KPI Summary")
        ln()
        ln("| KPI | Value | Notes |")
        ln("|-----|------:|-------|")
        for row in kpi_rows:
            ln(f"| {row.label} | {row.value} | {row.notes} |")
        ln()
        if churn_rows:
            ln("### Tickets Added After Sprint Start")
            ln()
            ln(
                "| Key | Summary | Assignee | Status | Sprint Started (IST) | Added To Sprint (IST) |"
            )
            ln(
                "|-----|---------|----------|--------|----------------------|-----------------------|"
            )
            for row in churn_rows:
                summary = row.summary.replace("|", "\\|")
                if len(summary) > 60:
                    summary = summary[:57].rstrip() + "…"
                ln(
                    f"| {row.key} | {summary} | {row.assignee} | {row.status} | "
                    f"{row.sprint_started_ist} | {row.added_to_sprint_ist} |"
                )
            ln()

    # ── Validation errors ───────────────────────────────────────────────
    ln("---")
    ln("## Validation: Sub-tasks With Remaining Work")
    ln()
    if not work_report.errors_child_remaining:
        ln("*No sub-tasks with non-zero remaining estimate.*")
    else:
        ln("| Ticket | Assignee | Parent | Remaining | Summary |")
        ln("|:-------|:---------|:-------|----------:|:--------|")
        for e in work_report.errors_child_remaining:
            pk = e.parent_key or "—"
            ln(
                f"| {e.key} | {e.assignee} | {pk} | {hours_to_jira(e.remaining_hours)} | "
                f"{e.summary[:45]} |"
            )
    ln()

    ln("---")
    ln("## Validation: Work Logged on Sub-tasks (Sprint Window)")
    ln()
    ln(
        f"Worklog entries with start date in **[{sprint_start.isoformat()}, {report_cap.isoformat()}]** "
        "on sub-task issues (should be empty when logging only on stories / tasks)."
    )
    ln()
    if not work_report.errors_child_worklogs:
        ln("*No worklogs on sub-tasks in this window.*")
    else:
        ln("| Ticket | Assignee | Parent | Total (h) | By author | Summary |")
        ln("|:-------|:---------|:-------|----------:|:----------|:--------|")
        for e in work_report.errors_child_worklogs:
            pk = e.parent_key or "—"
            detail = "; ".join(f"{a}: {h:.2f}h" for a, h in e.hours_by_author.items())
            ln(
                f"| {e.key} | {e.assignee} | {pk} | {e.total_hours:.2f} | {detail} | "
                f"{e.summary[:30]} |"
            )
    ln()

    # ── Sprint Completion & Velocity ─────────────────────────────────
    if issues is not None:
        assert team_completion is not None
        tc = team_completion
        ln("---")
        ln("## Sprint Completion & Velocity")
        ln()
        ln(
            "> **Sprint Completion Rate** — % of **Stories + Tasks** (excluding "
            "**excluded tickets**) considered **done** by sprint end. A ticket counts "
            "as done when its `status_category` is **Done** / **Complete**, **or** its "
            "`status` is **Resolved** (matches the Sprint Tickets table below). Reported "
            "at both **ticket** and **story-point** granularity. Target ≥ 90%.<br>"
            "**Velocity** — story points delivered ÷ team **effective person-days** "
            "(derived from sprint weeks, meeting reserve, and planned leaves). "
            "Sub-tasks are not counted; "
            "parent stories carry the points.<br>"
            "Unassigned tickets contribute to **team totals only**; they don't appear in "
            "the per-person table. Intended for **end-of-sprint** review."
        )
        ln()

        def _pct(p: float | None) -> str:
            return "—" if p is None else f"{int(round(p))}%"

        def _vel(v: float | None) -> str:
            return "—" if v is None else f"{v:.2f}"

        ln("### Team")
        ln()
        ln("| Metric | Value | Target |")
        ln("|--------|------:|:-------|")
        ln(f"| Tickets committed | {tc.tickets_committed} | — |")
        ln(f"| Tickets done | {tc.tickets_done} | — |")
        ln(f"| **Completion rate (tickets)** | **{_pct(tc.ticket_pct)}** | ≥ 90% |")
        ln(f"| Story points committed | {_fmt_sp(tc.sp_committed)} | — |")
        ln(f"| Story points delivered | {_fmt_sp(tc.sp_delivered)} | — |")
        ln(f"| **Completion rate (story points)** | **{_pct(tc.sp_pct)}** | ≥ 90% |")
        ln(f"| Effective person-days (team) | {_fmt_d(tc.effective_days)} | — |")
        ln(f"| **Velocity (SP / person-day)** | **{_vel(tc.velocity)}** | — |")
        ln()

        if tc.rows:
            ln("### Per-person")
            ln()
            ln(
                "| Person | Tickets done / committed | Tickets % | "
                "SP delivered / committed | SP % | SP / person-day |"
            )
            ln(
                "|--------|:-------------------------|--------:|"
                ":-------------------------|------:|----------------:|"
            )
            for r in tc.rows:
                ln(
                    f"| {r.name} | {r.tickets_done} / {r.tickets_committed} | "
                    f"{_pct(r.ticket_pct)} | "
                    f"{_fmt_sp(r.sp_delivered)} / {_fmt_sp(r.sp_committed)} | "
                    f"{_pct(r.sp_pct)} | {_vel(r.velocity)} |"
                )
            ln()

        # ── Sprint Tickets — Status & Remaining Work ─────────────────────
        ticket_rows = build_ticket_rows(config, issues)
        ln("---")
        ln("## Sprint Tickets — Status & Remaining Work")
        ln()
        ln(
            "> Every **Story / Task** in the sprint (sub-tasks aren't counted here, and "
            "**excluded tickets** are dropped). Sorted **not-done first**, then by status, "
            "then by key — so unfinished work is at the top of the list. Tickets in "
            "`Resolved` status are treated as effectively done and grouped with `Closed`. "
            "**Remaining (h)** is the issue's `remaining_estimate` from Jira; cells flagged "
            "**⚠** mean the ticket is effectively done but `Remaining > 0` (Jira hygiene "
            "fix-up — close the ticket with 0 remaining, or re-open if there is real work left)."
        )
        ln()
        if not ticket_rows:
            ln("*No Story / Task issues in the sprint.*")
            ln()
        else:
            ln(
                "| Key | Summary | Type | Assignee | Status | "
                "Estimate (h) | Remaining (h) | SP |"
            )
            ln(
                "|-----|---------|:----:|---------|--------|"
                "------:|------:|---:|"
            )
            for r in ticket_rows:
                summary = r.summary.replace("|", "\\|")
                if len(summary) > 60:
                    summary = summary[:57].rstrip() + "…"
                if r.remaining_hours is None:
                    rem_text = "—"
                else:
                    rem_text = f"{r.remaining_hours:.1f}"
                    if r.is_effectively_done and r.remaining_hours > 1e-6:
                        rem_text += " ⚠"
                sp_text = "—" if r.story_points <= 1e-9 else _fmt_sp(r.story_points)
                ln(
                    f"| {r.key} | {summary} | {r.type_} | {r.assignee} | {r.status} | "
                    f"{r.estimate_hours:.1f} | {rem_text} | {sp_text} |"
                )
            ln()

    # ── Placeholder for remaining metrics ─────────────────────────────────
    ln("---")
    ln()
    ln(
        "*Additional metrics (Jira hygiene score, ceremony effectiveness, remaining-work "
        "burndown line, …) are not calculated in this reporting mode yet.*"
    )
    ln()

    return "\n".join(lines)

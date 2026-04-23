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
) -> str:
    """Return markdown sprint report (story vs task logging model)."""
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
        "**Stories** vs **tasks** (non-story issue types) are in **two tables** below; each ends with a **team total** row. "
        "Each person/day cell lists **issue keys** (e.g. RSCDEV-1234) and hours under the daily total."
    )
    ln()

    def _emit_hours_table(title: str, bucket: str, total_label: str) -> None:
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
        hdr += f" **{total_label}** |"
        sep += "--------:|"
        ln(hdr)
        ln(sep)
        col_totals = [0.0] * len(display_dates)
        team_sum = 0.0
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
            team_sum += person_tot
            row += f" **{person_tot:.1f}** |"
            ln(row)
        total_row = "| **Team total** |"
        for j in range(len(display_dates)):
            total_row += f" **{col_totals[j]:.1f}** |"
        total_row += f" **{team_sum:.1f}** |"
        ln(total_row)
        ln()

    _emit_hours_table(
        "## Logged Hours by Person — Stories",
        "story",
        "Total (stories)",
    )
    _emit_hours_table(
        "## Logged Hours by Person — Tasks (non-story)",
        "task",
        "Total (tasks)",
    )

    # ── Daily log gaps (no story/task hours on a weekday) ─────
    ln("---")
    ln("## Weekdays With Zero Logged Hours (stories + tasks)")
    ln()
    ln(
        "For each included person, this lists **weekdays in the same date range as the tables above** "
        "where **no time was logged** on either **stories** or **tasks** "
        "(combined). It is a quick hygiene check, not an error list; same-day logging only on "
        "sub-tasks still counts as “missing” here because those hours are excluded from the tables."
    )
    ln()
    ln("| Name | Missing Days | Dates |")
    ln("|---|---|---|")
    for name in work_report.included_names:
        pdata = work_report.daily_story_task.get(name, {})
        missing = []
        for d in display_dates:
            cell = pdata.get(d, {"story": 0.0, "task": 0.0})
            if cell["story"] + cell["task"] < 1e-6:
                missing.append(d)
        if missing:
            date_strs = ", ".join(d.strftime("%b %d (%a)") for d in missing)
            ln(f"| {name} | {len(missing)} | {date_strs} |")
        else:
            ln(f"| {name} | 0 | All tracked days logged |")
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

    # ── Placeholder for future metrics ─────────────────────────────────
    ln("---")
    ln("## Other Metrics")
    ln()
    ln(
        "> **Under development:** Planned vs capacity, utilization, burndown / remaining work, "
        "velocity, completion rate, and related sections are not produced in this reporting mode yet."
    )
    ln()

    return "\n".join(lines)

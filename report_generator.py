"""
Text report generator.

Reads processed sprint data and produces a markdown report string.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from dataclasses import dataclass, field

from config_parser import SprintConfig
from utils import hours_to_jira, working_dates_in_range


@dataclass
class TicketReport:
    key: str
    summary: str
    status: str
    status_category: str
    issue_type: str  # "Parent", "Sub-task", "Standalone"
    assignee: str
    estimate_hours: float
    estimate_raw: str
    pre_sprint_logged_hours: float
    in_sprint_logged_hours: float
    planned_hours: float  # estimate - pre_sprint_logged
    story_points: float | None = None
    resolution_date: str = ""
    closed_before_sprint: bool = False
    daily_logged: dict = field(default_factory=dict)  # date -> hours


@dataclass
class PersonReport:
    name: str
    capacity_hours: float
    capacity_days: float
    leave_days: float
    tickets: list[TicketReport] = field(default_factory=list)
    total_planned_hours: float = 0.0
    total_logged_hours: float = 0.0
    daily_logs: dict = field(default_factory=dict)  # date -> hours


def _is_closed_before_sprint(issue: dict, sprint_start: date, in_sprint_hours: float, pre_sprint_hours: float) -> bool:
    """Check if a ticket was closed before the sprint started."""
    is_done = issue.get("status_category") == "Done" or issue.get("status") == "Closed"
    if not is_done:
        return False
    res_date_str = issue.get("resolution_date", "")
    if res_date_str and res_date_str < sprint_start.isoformat():
        return True
    if not res_date_str and in_sprint_hours == 0 and pre_sprint_hours > 0:
        return True
    return False


@dataclass
class SprintBuildResult:
    person_reports: list[PersonReport]
    carried_over: list[TicketReport]


def build_person_reports(
    config: SprintConfig,
    sprint_start: date,
    sprint_end: date,
    issues: list[dict],
    worklogs: dict[str, list[dict]],
    working_days: int,
) -> SprintBuildResult:
    """
    Process raw issue + worklog data into per-person report objects.

    Tickets that were closed before the sprint started are excluded from
    all calculations and returned separately in carried_over.
    """
    included = {m.name for m in config.team_members if m.included}
    leave_map = {l.name: l.days for l in config.planned_leaves}
    excl_map = {e.name: e.hours for e in config.other_exclusions}
    excluded_keys = set(config.excluded_tickets)
    parent_keys = {i["key"] for i in issues if i["type"] == "Parent"}

    effective_days = working_days - config.meeting_days_reserved

    person_map: dict[str, PersonReport] = {}
    for m in config.team_members:
        if not m.included:
            continue
        leave = leave_map.get(m.name, 0)
        excl_h = excl_map.get(m.name, 0)
        cap_days = effective_days - leave
        cap_hours = cap_days * 8 - excl_h
        person_map[m.name] = PersonReport(
            name=m.name,
            capacity_hours=cap_hours,
            capacity_days=cap_days,
            leave_days=leave,
        )

    carried_over: list[TicketReport] = []

    for issue in issues:
        key = issue["key"]
        if key in excluded_keys:
            continue
        if config.exclude_parent_estimates and key in parent_keys:
            continue
        assignee = issue["assignee"]
        if assignee not in included:
            continue

        wl_list = worklogs.get(key, [])
        pre_sprint = 0.0
        in_sprint = 0.0
        daily = defaultdict(float)

        for wl in wl_list:
            wl_date = date.fromisoformat(wl["started"][:10])
            wl_hours = wl["seconds"] / 3600.0
            author = wl["author"]
            if wl_date < sprint_start:
                pre_sprint += wl_hours
            elif wl_date <= sprint_end and author in included:
                in_sprint += wl_hours
                daily[wl_date] += wl_hours

        if _is_closed_before_sprint(issue, sprint_start, in_sprint, pre_sprint):
            carried_over.append(TicketReport(
                key=key,
                summary=issue["summary"][:70],
                status=issue["status"],
                status_category=issue["status_category"],
                issue_type=issue["type"],
                assignee=assignee,
                estimate_hours=issue["estimate_hours"],
                estimate_raw=issue["estimate_raw"],
                pre_sprint_logged_hours=pre_sprint,
                in_sprint_logged_hours=0,
                planned_hours=0,
                story_points=issue.get("story_points"),
                resolution_date=issue.get("resolution_date", ""),
                closed_before_sprint=True,
            ))
            continue

        planned = max(0, issue["estimate_hours"] - pre_sprint)

        tk = TicketReport(
            key=key,
            summary=issue["summary"][:70],
            status=issue["status"],
            status_category=issue["status_category"],
            issue_type=issue["type"],
            assignee=assignee,
            estimate_hours=issue["estimate_hours"],
            estimate_raw=issue["estimate_raw"],
            pre_sprint_logged_hours=pre_sprint,
            in_sprint_logged_hours=in_sprint,
            planned_hours=planned,
            story_points=issue.get("story_points"),
            resolution_date=issue.get("resolution_date", ""),
            closed_before_sprint=False,
            daily_logged=dict(daily),
        )

        pr = person_map[assignee]
        pr.tickets.append(tk)
        pr.total_planned_hours += planned
        pr.total_logged_hours += in_sprint

        for d, h in daily.items():
            pr.daily_logs[d] = pr.daily_logs.get(d, 0) + h

    reports = [person_map[m.name] for m in config.team_members if m.included and m.name in person_map]
    return SprintBuildResult(person_reports=reports, carried_over=carried_over)


def generate_text_report(
    config: SprintConfig,
    sprint_start: date,
    sprint_end: date,
    person_reports: list[PersonReport],
    total_issues: int,
    parent_count: int,
    sprint_goal: str = "",
    carried_over: list[TicketReport] | None = None,
) -> str:
    """Return a full markdown sprint report as a string."""
    if carried_over is None:
        carried_over = []
    all_dates = working_dates_in_range(sprint_start, sprint_end)
    lines: list[str] = []

    def ln(s=""):
        lines.append(s)

    ln(f"# Sprint Report: {config.sprint_name}")
    ln()
    ln(f"**Sprint Duration:** {sprint_start.strftime('%b %d, %Y')} \u2013 {sprint_end.strftime('%b %d, %Y')} ({config.sprint_duration_weeks} weeks)")
    report_label = config.report_date if config.report_date else "today"
    ln(f"**Report Date:** {report_label}")
    if sprint_goal:
        ln(f"**Sprint Goal:** {sprint_goal}")
    if carried_over:
        ln(f"**Note:** {len(carried_over)} ticket(s) closed before sprint start are excluded from this report.")
    ln()

    # ── Capacity table ───────────────────────────────────────────────────
    ln("---")
    ln("## Team Capacity")
    ln()
    ln("| Name | Eff. Days | Eff. Hours | Leave | Notes |")
    ln("|---|---|---|---|---|")
    total_cap = 0.0
    for pr in person_reports:
        total_cap += pr.capacity_hours
        note = f"{pr.leave_days:.0f}d leave" if pr.leave_days > 0 else ""
        ln(f"| {pr.name} | {pr.capacity_days:.0f}d | {pr.capacity_hours:.0f}h | {pr.leave_days:.0f} | {note} |")
    ln(f"| **TOTAL** | | **{total_cap:.0f}h** | | |")
    ln()
    ln(f"> {len(all_dates)} working days in sprint, {config.meeting_days_reserved:.0f}d reserved for meetings/ceremonies per person.")
    ln()

    # ── Planned vs Logged ────────────────────────────────────────────────
    ln("---")
    ln("## Planned vs Logged Work")
    ln()
    ln("| Name | Capacity | Planned | Logged | Delta | Utilization |")
    ln("|---|---|---|---|---|---|")
    t_planned = t_logged = 0.0
    for pr in person_reports:
        t_planned += pr.total_planned_hours
        t_logged += pr.total_logged_hours
        delta = pr.total_logged_hours - pr.total_planned_hours
        sign = "+" if delta >= 0 else ""
        util = (pr.total_logged_hours / pr.capacity_hours * 100) if pr.capacity_hours else 0
        plan_pct = (pr.total_planned_hours / pr.capacity_hours * 100) if pr.capacity_hours else 0
        ln(
            f"| {pr.name} | {pr.capacity_hours:.0f}h "
            f"| {pr.total_planned_hours:.0f}h ({plan_pct:.0f}%) "
            f"| {pr.total_logged_hours:.0f}h "
            f"| {sign}{delta:.0f}h "
            f"| {util:.0f}% |"
        )
    t_delta = t_logged - t_planned
    t_sign = "+" if t_delta >= 0 else ""
    t_util = (t_logged / total_cap * 100) if total_cap else 0
    ln(
        f"| **TEAM TOTAL** | **{total_cap:.0f}h** "
        f"| **{t_planned:.0f}h** "
        f"| **{t_logged:.0f}h** "
        f"| **{t_sign}{t_delta:.0f}h** "
        f"| **{t_util:.0f}%** |"
    )
    ln()

    # ── Per-ticket details ───────────────────────────────────────────────
    if config.show_per_ticket_details:
        ln("---")
        ln("## Per-Ticket Worklog Details")
        ln()
        for pr in person_reports:
            if not pr.tickets:
                continue
            ln(f"### {pr.name}")
            ln()
            ln("| Ticket | Status | Estimate | Planned | Logged | Delta | Summary |")
            ln("|---|---|---|---|---|---|---|")
            for tk in sorted(pr.tickets, key=lambda t: t.key):
                d = tk.in_sprint_logged_hours - tk.planned_hours
                ds = "+" if d >= 0 else ""
                logged_fmt = hours_to_jira(tk.in_sprint_logged_hours)
                if tk.in_sprint_logged_hours == 0 and tk.planned_hours > 0:
                    logged_fmt = f"**0h**"
                ln(
                    f"| {tk.key} | {tk.status} "
                    f"| {hours_to_jira(tk.estimate_hours)} "
                    f"| {hours_to_jira(tk.planned_hours)} "
                    f"| {logged_fmt} "
                    f"| {ds}{hours_to_jira(abs(d))} "
                    f"| {tk.summary[:50]} |"
                )
            ln()

    # ── Status distribution ──────────────────────────────────────────────
    ln("---")
    ln("## Ticket Status Distribution")
    ln()
    status_counts: dict[str, int] = defaultdict(int)
    total_tickets = 0
    closed_count = 0
    review_count = 0
    for pr in person_reports:
        for tk in pr.tickets:
            status_counts[tk.status] += 1
            total_tickets += 1
            if tk.status_category == "Done":
                closed_count += 1
            if "review" in tk.status.lower():
                review_count += 1

    ln("| Status | Count |")
    ln("|---|---|")
    for s, c in sorted(status_counts.items(), key=lambda x: -x[1]):
        ln(f"| {s} | {c} |")
    ln()
    if total_tickets:
        ln(f"**Completion:** {closed_count}/{total_tickets} closed ({closed_count/total_tickets*100:.0f}%), "
           f"{closed_count + review_count}/{total_tickets} closed+review ({(closed_count + review_count)/total_tickets*100:.0f}%)")
    ln()

    # ── Daily log gaps ───────────────────────────────────────────────────
    if config.show_daily_log_gaps:
        ln("---")
        ln("## Daily Log Gaps")
        ln()
        ln("| Name | Missing Days | Dates |")
        ln("|---|---|---|")
        for pr in person_reports:
            missing = [d for d in all_dates if pr.daily_logs.get(d, 0) == 0]
            if missing:
                date_strs = ", ".join(d.strftime("%b %d (%a)") for d in missing)
                ln(f"| {pr.name} | {len(missing)} | {date_strs} |")
            else:
                ln(f"| {pr.name} | 0 | All days logged |")
        ln()

    # ── Sprint Completion Rate & Velocity ────────────────────────────────
    ln("---")
    ln("## Sprint Completion & Velocity")
    ln()

    all_tickets = [tk for pr in person_reports for tk in pr.tickets]
    committed = len(all_tickets)
    completed_tks = [tk for tk in all_tickets if tk.status_category == "Done"]
    completed_count = len(completed_tks)
    in_review_tks = [tk for tk in all_tickets if "review" in tk.status.lower()]
    completion_rate = (completed_count / committed * 100) if committed else 0
    completion_rate_incl_review = (
        (completed_count + len(in_review_tks)) / committed * 100
    ) if committed else 0

    has_story_points = any(tk.story_points is not None for tk in all_tickets)
    sp_committed = sum(tk.story_points for tk in all_tickets if tk.story_points is not None)
    sp_completed = sum(tk.story_points for tk in completed_tks if tk.story_points is not None)
    hours_committed = sum(tk.estimate_hours for tk in all_tickets)
    hours_completed = sum(tk.estimate_hours for tk in completed_tks)
    total_man_days = sum(pr.capacity_days for pr in person_reports)

    ln("### Sprint Completion Rate")
    ln()
    ln("| Metric | Value | Target |")
    ln("|--------|:-----:|:------:|")
    rate_status = "**ON TRACK**" if completion_rate >= 90 else ("AT RISK" if completion_rate >= 70 else "BEHIND")
    ln(f"| Completed / Committed | {completed_count} / {committed} ({completion_rate:.0f}%) | ≥ 90% |")
    ln(f"| Completed + In Review | {completed_count + len(in_review_tks)} / {committed} ({completion_rate_incl_review:.0f}%) | |")
    ln(f"| Status | {rate_status} | |")
    ln()

    ln("### Sprint Velocity")
    ln()

    if has_story_points:
        vel = (sp_completed / total_man_days) if total_man_days else 0
        ln("| Metric | Value |")
        ln("|--------|:-----:|")
        ln(f"| Story Points committed | {sp_committed:.0f} SP |")
        ln(f"| Story Points completed | {sp_completed:.0f} SP |")
        ln(f"| Team man-days available | {total_man_days:.0f} days |")
        ln(f"| **Velocity (SP / man-day)** | **{vel:.2f}** |")
        ln()
    else:
        vel = (hours_completed / total_man_days) if total_man_days else 0
        ln("| Metric | Value |")
        ln("|--------|:-----:|")
        ln(f"| Estimated hours committed | {hours_committed:.0f}h |")
        ln(f"| Estimated hours completed | {hours_completed:.0f}h |")
        ln(f"| Team man-days available | {total_man_days:.0f} days |")
        ln(f"| **Velocity (est. hours / man-day)** | **{vel:.2f}** |")
        ln()
        ln("> *Story points not configured in Jira. Velocity uses estimated hours of completed items.*")
        ln()

    # Per-person velocity breakdown
    ln("### Velocity by Team Member")
    ln()
    if has_story_points:
        ln("| Person | Man-days | SP Committed | SP Completed | Velocity (SP/day) | Completion |")
        ln("|--------|:--------:|:------------:|:------------:|:-----------------:|:----------:|")
    else:
        ln("| Person | Man-days | Hours Committed | Hours Completed | Velocity (h/day) | Completion |")
        ln("|--------|:--------:|:---------------:|:---------------:|:----------------:|:----------:|")

    for pr in person_reports:
        p_completed = [tk for tk in pr.tickets if tk.status_category == "Done"]

        if has_story_points:
            p_sp_c = sum(tk.story_points for tk in pr.tickets if tk.story_points is not None)
            p_sp_d = sum(tk.story_points for tk in p_completed if tk.story_points is not None)
            p_vel = (p_sp_d / pr.capacity_days) if pr.capacity_days else 0
            p_rate = (p_sp_d / p_sp_c * 100) if p_sp_c else 0
            ln(f"| {pr.name} | {pr.capacity_days:.0f} | {p_sp_c:.0f} | {p_sp_d:.0f} | {p_vel:.2f} | {p_sp_d:.0f}/{p_sp_c:.0f} ({p_rate:.0f}%) |")
        else:
            p_h_c = sum(tk.estimate_hours for tk in pr.tickets)
            p_h_d = sum(tk.estimate_hours for tk in p_completed)
            p_vel = (p_h_d / pr.capacity_days) if pr.capacity_days else 0
            p_rate = (p_h_d / p_h_c * 100) if p_h_c else 0
            ln(f"| {pr.name} | {pr.capacity_days:.0f} | {p_h_c:.0f}h | {p_h_d:.0f}h | {p_vel:.1f} | {p_h_d:.0f}h/{p_h_c:.0f}h ({p_rate:.0f}%) |")

    team_vel = vel
    if has_story_points:
        sp_rate = (sp_completed / sp_committed * 100) if sp_committed else 0
        ln(f"| **TEAM** | **{total_man_days:.0f}** | **{sp_committed:.0f}** | **{sp_completed:.0f}** | **{team_vel:.2f}** | **{sp_completed:.0f}/{sp_committed:.0f} ({sp_rate:.0f}%)** |")
    else:
        h_rate = (hours_completed / hours_committed * 100) if hours_committed else 0
        ln(f"| **TEAM** | **{total_man_days:.0f}** | **{hours_committed:.0f}h** | **{hours_completed:.0f}h** | **{team_vel:.1f}** | **{hours_completed:.0f}h/{hours_committed:.0f}h ({h_rate:.0f}%)** |")
    ln()

    # ── Carried-over closed tickets (for info only) ──────────────────────
    if carried_over:
        ln("### Carried-Over Closed Tickets (Excluded)")
        ln()
        ln("These tickets were closed before the sprint started and are **excluded from all calculations**.")
        ln()
        ln("| Ticket | Assignee | Estimate | Summary |")
        ln("|:-------|:---------|:--------:|:--------|")
        for tk in sorted(carried_over, key=lambda t: t.assignee):
            ln(f"| {tk.key} | {tk.assignee} | {hours_to_jira(tk.estimate_hours)} | {tk.summary[:55]} |")
        pre_h = sum(tk.estimate_hours for tk in carried_over)
        ln(f"| | **Total: {len(carried_over)} tickets** | **{hours_to_jira(pre_h)}** | |")
        ln()

    # ── Summary ──────────────────────────────────────────────────────────
    ln("---")
    ln("## Sprint Health Summary")
    ln()
    unstarted = sum(
        1 for pr in person_reports for tk in pr.tickets
        if tk.in_sprint_logged_hours == 0 and tk.planned_hours > 0
    )
    overcommitted = sum(
        1 for pr in person_reports
        if pr.total_planned_hours > pr.capacity_hours * 1.05
    )
    ln("| Metric | Value |")
    ln("|---|---|")
    ln(f"| Team utilization | {t_util:.0f}% ({t_logged:.0f}h / {total_cap:.0f}h) |")
    plan_adh = (t_logged / t_planned * 100) if t_planned else 0
    ln(f"| Plan adherence | {plan_adh:.0f}% ({t_logged:.0f}h / {t_planned:.0f}h) |")
    ln(f"| Sprint completion rate | {completion_rate:.0f}% ({completed_count}/{committed}) — Target: ≥ 90% |")
    vel_label = f"{team_vel:.2f} SP/man-day" if has_story_points else f"{team_vel:.1f} est-hours/man-day"
    ln(f"| Sprint velocity | {vel_label} |")
    if carried_over:
        ln(f"| Carried-over closed (excluded) | {len(carried_over)} tickets |")
    ln(f"| Tickets closed | {closed_count} / {total_tickets} ({closed_count/total_tickets*100:.0f}%) |" if total_tickets else "| Tickets closed | 0 |")
    ln(f"| Tickets closed+review | {closed_count + review_count} / {total_tickets} ({(closed_count+review_count)/total_tickets*100:.0f}%) |" if total_tickets else "")
    ln(f"| Unstarted (with planned hours) | {unstarted} |")
    ln(f"| Overcommitted members | {overcommitted} |")
    ln()

    return "\n".join(lines)


# ── Cycle Time Section ───────────────────────────────────────────────────────

def _ct_fmt(hours: float | None) -> str:
    """Format business hours into a compact human-readable string."""
    if hours is None:
        return "N/A"
    if hours < 1:
        return f"{hours * 60:.0f}m"
    if hours < 24:
        return f"{hours:.1f}h"
    days = hours / 24
    if days < 7:
        return f"{days:.1f}d"
    return f"{days / 7:.1f}w"


def _ct_fmt_detail(hours: float | None) -> str:
    if hours is None:
        return "N/A"
    if hours < 1:
        return f"{hours * 60:.0f} min"
    if hours < 24:
        return f"{hours:.1f} hours"
    days = hours / 24
    return f"{days:.1f} days ({hours:.0f}h)"


def _ct_avg(values: list[float]) -> float | None:
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else None


def generate_cycle_time_section(cycle_data: list[dict], repo: str = "") -> str:
    """Generate a markdown section for PR cycle time metrics.

    Parameters
    ----------
    cycle_data : list[dict]
        List of PR metric dicts (from cycle_time_data_*.json).
    repo : str
        GitHub repo identifier for display.
    """
    lines: list[str] = []

    def ln(s=""):
        lines.append(s)

    ln("---")
    ln("## PR Cycle Time")
    ln()
    if repo:
        ln(f"**Repo:** `{repo}`  ")
    ln(f"**PRs analyzed:** {len(cycle_data)}  ")
    ln(f"*All times are business hours (weekends excluded).*")
    ln()

    if not cycle_data:
        ln("_No PR data available._")
        ln()
        return "\n".join(lines)

    by_person: dict[str, list[dict]] = defaultdict(list)
    for pr in cycle_data:
        by_person[pr.get("assignee", "Unassigned")].append(pr)

    # ── Summary table ────────────────────────────────────────────────────
    ln("### Cycle Time by Team Member")
    ln()
    ln("| Person | PRs | Avg Coding | Avg Pickup | Avg Review | Avg Cycle |")
    ln("|--------|:---:|:----------:|:----------:|:----------:|:---------:|")

    team_coding: list[float] = []
    team_pickup: list[float] = []
    team_review: list[float] = []
    team_cycle: list[float] = []

    for person in sorted(by_person.keys()):
        prs = by_person[person]
        c = [p["coding_time_hours"] for p in prs if p.get("coding_time_hours") is not None]
        p_ = [p["pickup_time_hours"] for p in prs if p.get("pickup_time_hours") is not None]
        r = [p["review_time_hours"] for p in prs if p.get("review_time_hours") is not None]
        cy = [p["cycle_time_hours"] for p in prs if p.get("cycle_time_hours") is not None]
        team_coding.extend(c)
        team_pickup.extend(p_)
        team_review.extend(r)
        team_cycle.extend(cy)
        ln(
            f"| {person} | {len(prs)} | {_ct_fmt(_ct_avg(c))} | "
            f"{_ct_fmt(_ct_avg(p_))} | {_ct_fmt(_ct_avg(r))} | "
            f"{_ct_fmt(_ct_avg(cy))} |"
        )

    ln(
        f"| **TEAM AVERAGE** | **{len(cycle_data)}** | "
        f"**{_ct_fmt(_ct_avg(team_coding))}** | "
        f"**{_ct_fmt(_ct_avg(team_pickup))}** | "
        f"**{_ct_fmt(_ct_avg(team_review))}** | "
        f"**{_ct_fmt(_ct_avg(team_cycle))}** |"
    )
    ln()
    ln("> **Coding** = First commit → PR creation | "
       "**Pickup** = PR created → First human review | "
       "**Review** = First review → Merge | "
       "**Cycle** = First commit → Merge")
    ln()

    # ── Per-person PR detail ─────────────────────────────────────────────
    ln("### PR Details by Person")
    ln()

    for person in sorted(by_person.keys()):
        prs = by_person[person]
        ln(f"**{person}**")
        ln()
        ln("| PR | Jira | State | Coding | Pickup | Review | Cycle | Size | Commits | Reviews |")
        ln("|:---|:-----|:-----:|:------:|:------:|:------:|:-----:|:----:|:-------:|:-------:|")

        for p in sorted(prs, key=lambda x: x.get("created_at") or ""):
            state = p.get("state", "").lower()
            url = p.get("url", "")
            num = p.get("pr_number", "?")
            ln(
                f"| [#{num}]({url}) | {p.get('jira_key', '')} | {state} | "
                f"{_ct_fmt(p.get('coding_time_hours'))} | "
                f"{_ct_fmt(p.get('pickup_time_hours'))} | "
                f"{_ct_fmt(p.get('review_time_hours'))} | "
                f"{_ct_fmt(p.get('cycle_time_hours'))} | "
                f"+{p.get('additions', 0)}/-{p.get('deletions', 0)} | "
                f"{p.get('total_commits', 0)} | "
                f"{p.get('total_human_reviews', 0)} |"
            )

        ln()

    # ── Insights ─────────────────────────────────────────────────────────
    ln("### Cycle Time Insights")
    ln()

    merged = [p for p in cycle_data if p.get("cycle_time_hours") is not None]
    if merged:
        fastest = min(merged, key=lambda p: p["cycle_time_hours"])
        slowest = max(merged, key=lambda p: p["cycle_time_hours"])
        ln(
            f"- **Fastest merge:** [#{fastest['pr_number']}]({fastest.get('url', '')}) "
            f"({fastest.get('jira_key', '')}) — {_ct_fmt_detail(fastest['cycle_time_hours'])}"
        )
        ln(
            f"- **Slowest merge:** [#{slowest['pr_number']}]({slowest.get('url', '')}) "
            f"({slowest.get('jira_key', '')}) — {_ct_fmt_detail(slowest['cycle_time_hours'])}"
        )

    if team_coding and team_pickup and team_review:
        vals = [
            ("Coding", _ct_avg(team_coding)),
            ("Pickup", _ct_avg(team_pickup)),
            ("Review", _ct_avg(team_review)),
        ]
        vals = [(n, v) for n, v in vals if v is not None]
        if vals:
            bottleneck = max(vals, key=lambda x: x[1])
            ln(f"- **Biggest bottleneck:** {bottleneck[0]} Time "
               f"({_ct_fmt_detail(bottleneck[1])} avg)")

    open_prs = [p for p in cycle_data if p.get("state") == "OPEN"]
    if open_prs:
        ln(f"- **Open PRs awaiting review/merge:** {len(open_prs)}")
        for p in open_prs:
            created = p.get("created_at")
            age = ""
            if created:
                try:
                    dt = datetime.fromisoformat(created)
                    age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                    age = f" — open for {_ct_fmt_detail(age_h)}"
                except ValueError:
                    pass
            reviewed = "reviewed" if p.get("first_human_review_at") else "**no review yet**"
            ln(f"  - [#{p['pr_number']}]({p.get('url', '')}) ({p.get('jira_key', '')}){age}, {reviewed}")

    ln()
    return "\n".join(lines)

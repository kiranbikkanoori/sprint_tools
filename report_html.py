"""Styled HTML sprint report renderer (light/dark aware)."""

from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path

from config_parser import SprintConfig
from report_generator import (
    REASON_NOT_STARTED,
    SprintWorkReport,
    TeamCompletion,
    _fmt_d,
    _fmt_sp,
    _log_window_end,
    _remaining_hours_by_assignee,
    build_backlog_churn_rows,
    build_capacity_hours_by_person,
    build_completion_velocity,
    build_effective_days_by_person,
    build_kpi_summary,
    build_ticket_rows,
)
from report_style import THEME_TOGGLE_SCRIPT, report_css_browser, report_css_for_theme
from utils import hours_to_jira, working_dates_in_range


def _pct(p: float | None, *, planning_mode: bool = False) -> str:
    if planning_mode:
        return REASON_NOT_STARTED
    return "—" if p is None else f"{int(round(p))}%"


def _vel(v: float | None, *, planning_mode: bool = False) -> str:
    if planning_mode:
        return REASON_NOT_STARTED
    return "—" if v is None else f"{v:.2f}"


def _planning_hours_table_html(
    work_report: SprintWorkReport,
    remaining_by_name: dict[str, float],
    capacity_by_name: dict[str, float],
) -> str:
    parts: list[str] = [
        "<table><thead><tr>"
        "<th>Person</th>"
        "<th class='num'>Remaining (h)</th>"
        "<th class='num'>Capacity (h)</th>"
        "</tr></thead><tbody>"
    ]
    team_rem = 0.0
    team_cap = 0.0
    for name in work_report.included_names:
        rem_h = float(remaining_by_name.get(name, 0.0))
        cap_h = float(capacity_by_name.get(name, 0.0))
        team_rem += rem_h
        team_cap += cap_h
        parts.append(
            f"<tr><td>{escape(name)}</td>"
            f'<td class="num"><strong>{rem_h:.1f}</strong></td>'
            f'<td class="num"><strong>{cap_h:.1f}</strong></td></tr>'
        )
    parts.append(
        '<tr class="total"><td>Team total</td>'
        f'<td class="num">{team_rem:.1f}</td>'
        f'<td class="num">{team_cap:.1f}</td></tr></tbody></table>'
    )
    return "".join(parts)


def _day_cell_html(total_h: float, ticket_hours: dict[str, float], *, max_tickets: int = 14) -> str:
    if total_h < 1e-6 and not ticket_hours:
        return "0.0"
    parts = [f"<strong>{total_h:.1f}</strong>"]
    items = sorted(ticket_hours.items(), key=lambda x: (-x[1], x[0]))
    positive = [(k, h) for k, h in items if h >= 1e-6]
    for idx, (key, hrs) in enumerate(positive):
        if idx >= max_tickets:
            parts.append(f"<br>• <em>…and {len(positive) - max_tickets} more</em>")
            break
        parts.append(f"<br>• <code>{escape(key)}</code> {hrs:.1f}h")
    return "".join(parts)


def _hours_table_html(
    work_report: SprintWorkReport,
    display_dates: list[date],
    bucket: str,
    logged_label: str,
    remaining_by_name: dict[str, float],
) -> str:
    if not display_dates:
        return '<p class="empty">No working days in range.</p>'

    parts: list[str] = ['<table><thead><tr><th>Person</th>']
    for d in display_dates:
        parts.append(f'<th class="num">{escape(d.strftime("%b %d"))} (h)</th>')
    parts.append(
        f'<th class="num">{escape(logged_label)}</th>'
        f'<th class="num">Remaining (h)</th></tr></thead><tbody>'
    )

    col_totals = [0.0] * len(display_dates)
    team_logged = 0.0
    team_remaining = 0.0
    tdetails = work_report.daily_ticket_hours
    for name in work_report.included_names:
        parts.append(f"<tr><td>{escape(name)}</td>")
        person_tot = 0.0
        pdata = work_report.daily_story_task.get(name, {})
        for j, d in enumerate(display_dates):
            cell = pdata.get(d, {"story": 0.0, "task": 0.0})
            h = cell[bucket]
            col_totals[j] += h
            person_tot += h
            tickets_for_cell = tdetails.get(name, {}).get(d, {}).get(bucket, {})
            parts.append(f'<td class="num">{_day_cell_html(h, tickets_for_cell)}</td>')
        rem_h = float(remaining_by_name.get(name, 0.0))
        team_logged += person_tot
        team_remaining += rem_h
        parts.append(
            f'<td class="num"><strong>{person_tot:.1f}</strong></td>'
            f'<td class="num"><strong>{rem_h:.1f}</strong></td></tr>'
        )

    parts.append('<tr class="total"><td>Team total</td>')
    for j in range(len(display_dates)):
        parts.append(f'<td class="num">{col_totals[j]:.1f}</td>')
    parts.append(
        f'<td class="num">{team_logged:.1f}</td>'
        f'<td class="num">{team_remaining:.1f}</td></tr></tbody></table>'
    )
    return "".join(parts)


def generate_html_report(
    config: SprintConfig,
    sprint_start: date,
    sprint_end: date,
    work_report: SprintWorkReport,
    sprint_goal: str = "",
    *,
    issues: list[dict] | None = None,
    sprint_start_raw: str | None = None,
    chart_path: str | Path | None = None,
    theme: str | None = None,
    include_theme_toggle: bool = True,
    start_label: str | None = None,
    end_label: str | None = None,
    planning_mode: bool = False,
) -> str:
    """
    Return a self-contained HTML sprint report.

    ``chart_path`` is accepted for backward compatibility but is **not** embedded;
    the hours bar chart was removed from the report UI.

    ``theme``:
      - ``None`` — browser dual-theme CSS (OS preference + optional toggle)
      - ``"light"`` / ``"dark"`` — resolved single-theme CSS (GUI preview)

    ``start_label`` / ``end_label`` override the duration chip (use ``N/A``
    when Jira did not provide dates).
    """
    _ = chart_path  # intentionally unused — chart no longer embedded in HTML
    all_dates = working_dates_in_range(sprint_start, sprint_end)
    report_cap = _log_window_end(
        sprint_end,
        date.fromisoformat(config.report_date) if config.report_date else None,
    )
    display_dates = [] if planning_mode else [d for d in all_dates if d <= report_cap]

    team_completion: TeamCompletion | None = None
    kpi_rows = []
    churn_rows = []
    ticket_rows = []
    if issues is not None:
        effective_days_by_name = build_effective_days_by_person(config, work_report)
        team_completion = build_completion_velocity(config, issues, effective_days_by_name)
        kpi_rows = build_kpi_summary(
            config, issues, team_completion, planning_mode=planning_mode
        )
        churn_rows = (
            [] if planning_mode else build_backlog_churn_rows(config, issues, sprint_start_raw)
        )
        ticket_rows = build_ticket_rows(config, issues)

    report_label = config.report_date if config.report_date else "today"
    start_txt = start_label or sprint_start.strftime("%b %d, %Y")
    end_txt = end_label or sprint_end.strftime("%b %d, %Y")
    duration = (
        f"{start_txt} – {end_txt} "
        f"({config.sprint_duration_weeks} weeks)"
    )
    goal_clip = (sprint_goal or "").strip()
    if len(goal_clip) > 280:
        goal_clip = goal_clip[:277].rstrip() + "…"

    chips = ""
    if team_completion is not None:
        if planning_mode:
            chips = (
                f'<div class="chips">'
                f'<span class="chip">Planning view</span>'
                f'<span class="chip">{escape(REASON_NOT_STARTED)}</span>'
                f"</div>"
            )
        else:
            chips = (
                f'<div class="chips">'
                f'<span class="chip">Completion {_pct(team_completion.ticket_pct)}</span>'
                f'<span class="chip">Velocity {_vel(team_completion.velocity)} SP/day</span>'
                f"</div>"
            )

    toggle = ""
    if include_theme_toggle and theme is None:
        toggle = (
            '<div class="theme-toggle">'
            '<button type="button" onclick="setReportTheme(\'light\')">Light</button>'
            '<button type="button" onclick="setReportTheme(\'dark\')">Dark</button>'
            '<button type="button" onclick="setReportTheme(\'auto\')">Auto</button>'
            "</div>"
        )

    css = report_css_for_theme(theme) if theme in ("light", "dark") else report_css_browser()
    script = THEME_TOGGLE_SCRIPT if (include_theme_toggle and theme is None) else ""
    data_theme_attr = f' data-theme="{escape(theme)}"' if theme in ("light", "dark") else ""

    body: list[str] = []
    body.append('<div class="report-header">')
    body.append(toggle)
    body.append(f"<h1>Sprint Report: {escape(config.sprint_name)}</h1>")
    body.append(f'<p class="meta"><strong>Sprint Duration:</strong> {escape(duration)}</p>')
    body.append(f'<p class="meta"><strong>Report Date:</strong> {escape(report_label)}</p>')
    if goal_clip:
        body.append(f'<p class="goal"><strong>Sprint Goal:</strong> {escape(goal_clip)}</p>')
    body.append(chips)
    body.append("</div>")

    rem_story = _remaining_hours_by_assignee(config, issues or [], bucket="story")
    rem_task = _remaining_hours_by_assignee(config, issues or [], bucket="task")
    capacity = build_capacity_hours_by_person(config, work_report.included_names)

    if planning_mode:
        body.append(
            f'<p class="note"><strong>Planning view</strong> — {escape(REASON_NOT_STARTED)}. '
            "Worklogs are not counted. Tables below show Remaining vs Capacity only.</p>"
        )
        body.append("<section>")
        body.append("<h2>Stories — remaining &amp; capacity</h2>")
        body.append(_planning_hours_table_html(work_report, rem_story, capacity))
        body.append("</section>")
        body.append("<section>")
        body.append("<h2>Tasks (non-story) — remaining &amp; capacity</h2>")
        body.append(_planning_hours_table_html(work_report, rem_task, capacity))
        body.append("</section>")
    else:
        body.append(
            '<p class="note">Worklog source: by <strong>worklog author</strong>, for team members '
            "with Include = Yes. Weekday columns cover "
            f"<strong>[{sprint_start.isoformat()}, {report_cap.isoformat()}]</strong>. "
            "<strong>Logged</strong> comes from worklogs; <strong>Remaining (h)</strong> sums each "
            "assignee’s Story/Task <strong>remaining estimates</strong> in Jira (not original estimate). "
            "Sub-task logs appear only under validation.</p>"
        )
        body.append("<section>")
        body.append("<h2>Stories — logged hours &amp; remaining</h2>")
        body.append(
            _hours_table_html(
                work_report, display_dates, "story", "Logged (h)", rem_story,
            )
        )
        body.append("</section>")
        body.append("<section>")
        body.append("<h2>Tasks (non-story) — logged hours &amp; remaining</h2>")
        body.append(
            _hours_table_html(
                work_report, display_dates, "task", "Logged (h)", rem_task,
            )
        )
        body.append("</section>")

    if issues is not None and team_completion is not None:
        body.append("<section>")
        body.append("<h2>Sprint KPI Summary</h2>")
        body.append(
            "<table><thead><tr><th>KPI</th><th>Value</th><th>Notes</th></tr></thead><tbody>"
        )
        for row in kpi_rows:
            body.append(
                f"<tr><td>{escape(row.label)}</td>"
                f"<td><strong>{escape(str(row.value))}</strong></td>"
                f"<td>{escape(row.notes)}</td></tr>"
            )
        body.append("</tbody></table>")
        if churn_rows:
            body.append("<h3>Tickets Added After Sprint Start</h3>")
            body.append(
                "<table><thead><tr>"
                "<th>Key</th><th>Summary</th><th>Assignee</th><th>Status</th>"
                "<th>Sprint Started (IST)</th><th>Added To Sprint (IST)</th>"
                "</tr></thead><tbody>"
            )
            for row in churn_rows:
                summary = row.summary
                if len(summary) > 60:
                    summary = summary[:57].rstrip() + "…"
                body.append(
                    f"<tr><td><code>{escape(row.key)}</code></td>"
                    f"<td>{escape(summary)}</td>"
                    f"<td>{escape(row.assignee)}</td>"
                    f"<td>{escape(row.status)}</td>"
                    f"<td>{escape(row.sprint_started_ist)}</td>"
                    f"<td>{escape(row.added_to_sprint_ist)}</td></tr>"
                )
            body.append("</tbody></table>")
        body.append("</section>")

    body.append("<section>")
    body.append("<h2>Validation: Sub-tasks With Remaining Work</h2>")
    if not work_report.errors_child_remaining:
        body.append('<p class="empty">No sub-tasks with non-zero remaining estimate.</p>')
    else:
        body.append(
            "<table><thead><tr>"
            "<th>Ticket</th><th>Assignee</th><th>Parent</th>"
            "<th class='num'>Remaining</th><th>Summary</th>"
            "</tr></thead><tbody>"
        )
        for e in work_report.errors_child_remaining:
            pk = e.parent_key or "—"
            body.append(
                f"<tr><td><code>{escape(e.key)}</code></td>"
                f"<td>{escape(e.assignee)}</td>"
                f"<td>{escape(pk)}</td>"
                f"<td class='num'>{escape(hours_to_jira(e.remaining_hours))}</td>"
                f"<td>{escape(e.summary[:45])}</td></tr>"
            )
        body.append("</tbody></table>")
    body.append("</section>")

    body.append("<section>")
    body.append("<h2>Validation: Work Logged on Sub-tasks (Sprint Window)</h2>")
    if planning_mode:
        body.append(
            f'<p class="empty">{escape(REASON_NOT_STARTED)} — no worklog window.</p>'
        )
    else:
        body.append(
            f'<p class="muted">Worklogs on sub-tasks in '
            f"[{sprint_start.isoformat()}, {report_cap.isoformat()}]. "
            "Should be empty when logging only on stories/tasks.</p>"
        )
        if not work_report.errors_child_worklogs:
            body.append('<p class="empty">No worklogs on sub-tasks in this window.</p>')
        else:
            body.append(
                "<table><thead><tr>"
                "<th>Ticket</th><th>Assignee</th><th>Parent</th>"
                "<th class='num'>Total (h)</th><th>By author</th><th>Summary</th>"
                "</tr></thead><tbody>"
            )
            for e in work_report.errors_child_worklogs:
                pk = e.parent_key or "—"
                detail = "; ".join(f"{a}: {h:.2f}h" for a, h in e.hours_by_author.items())
                body.append(
                    f"<tr><td><code>{escape(e.key)}</code></td>"
                    f"<td>{escape(e.assignee)}</td>"
                    f"<td>{escape(pk)}</td>"
                    f"<td class='num'>{e.total_hours:.2f}</td>"
                    f"<td>{escape(detail)}</td>"
                    f"<td>{escape(e.summary[:30])}</td></tr>"
                )
            body.append("</tbody></table>")
    body.append("</section>")

    if team_completion is not None:
        tc = team_completion
        body.append("<section>")
        body.append("<h2>Sprint Completion &amp; Velocity</h2>")
        body.append(
            '<p class="note"><strong>Completion</strong> — Stories + Tasks done by sprint end '
            "(status category Done/Complete, or status Resolved). Target ≥ 90%.<br>"
            "<strong>Velocity</strong> — story points delivered ÷ effective person-days "
            "(sprint weeks × 5 − meeting reserve − planned leaves).</p>"
        )
        body.append("<h3>Team</h3>")
        body.append(
            "<table><thead><tr><th>Metric</th><th>Value</th><th>Target</th>"
            "</tr></thead><tbody>"
        )
        team_rows = [
            ("Tickets committed", str(tc.tickets_committed), "—"),
            ("Tickets done", str(tc.tickets_done), "—"),
            ("Completion rate (tickets)", _pct(tc.ticket_pct, planning_mode=planning_mode), "≥ 90%"),
            ("Story points committed", _fmt_sp(tc.sp_committed), "—"),
            ("Story points delivered", _fmt_sp(tc.sp_delivered), "—"),
            ("Completion rate (story points)", _pct(tc.sp_pct, planning_mode=planning_mode), "≥ 90%"),
            ("Effective person-days (team)", _fmt_d(tc.effective_days), "—"),
            ("Velocity (SP / person-day)", _vel(tc.velocity, planning_mode=planning_mode), "—"),
        ]
        for label, value, target in team_rows:
            strong = "Completion" in label or "Velocity" in label
            val_html = f"<strong>{escape(value)}</strong>" if strong else escape(value)
            body.append(
                f"<tr><td>{escape(label)}</td>"
                f"<td>{val_html}</td>"
                f"<td>{escape(target)}</td></tr>"
            )
        body.append("</tbody></table>")

        if tc.rows:
            body.append("<h3>Per-person</h3>")
            body.append(
                "<table><thead><tr>"
                "<th>Person</th>"
                "<th>Tickets done / committed</th><th>Tickets %</th>"
                "<th>SP delivered / committed</th><th>SP %</th>"
                "<th>SP / person-day</th>"
                "</tr></thead><tbody>"
            )
            for r in tc.rows:
                body.append(
                    f"<tr><td>{escape(r.name)}</td>"
                    f"<td>{r.tickets_done} / {r.tickets_committed}</td>"
                    f"<td>{_pct(r.ticket_pct, planning_mode=planning_mode)}</td>"
                    f"<td>{_fmt_sp(r.sp_delivered)} / {_fmt_sp(r.sp_committed)}</td>"
                    f"<td>{_pct(r.sp_pct, planning_mode=planning_mode)}</td>"
                    f"<td>{_vel(r.velocity, planning_mode=planning_mode)}</td></tr>"
                )
            body.append("</tbody></table>")
        body.append("</section>")

        body.append("<section>")
        body.append("<h2>Sprint Tickets — Status &amp; Remaining Work</h2>")
        body.append(
            '<p class="note">Every Story/Task in the sprint (excluded tickets dropped). '
            "Unfinished first. <strong>⚠</strong> means done/Resolved but remaining hours &gt; 0.</p>"
        )
        if not ticket_rows:
            body.append('<p class="empty">No Story / Task issues in the sprint.</p>')
        else:
            body.append(
                "<table><thead><tr>"
                "<th>Key</th><th>Summary</th><th>Type</th><th>Assignee</th><th>Status</th>"
                "<th class='num'>Estimate (h)</th><th class='num'>Remaining (h)</th>"
                "<th class='num'>SP</th>"
                "</tr></thead><tbody>"
            )
            for r in ticket_rows:
                summary = r.summary.replace("|", " ")
                if len(summary) > 60:
                    summary = summary[:57].rstrip() + "…"
                warn = False
                if r.remaining_hours is None:
                    rem_text = "—"
                else:
                    rem_text = f"{r.remaining_hours:.1f}"
                    if r.is_effectively_done and r.remaining_hours > 1e-6:
                        rem_text += " ⚠"
                        warn = True
                sp_text = "—" if r.story_points <= 1e-9 else _fmt_sp(r.story_points)
                tr_cls = ' class="warn"' if warn else ""
                body.append(
                    f"<tr{tr_cls}><td><code>{escape(r.key)}</code></td>"
                    f"<td>{escape(summary)}</td>"
                    f"<td>{escape(r.type_)}</td>"
                    f"<td>{escape(r.assignee)}</td>"
                    f"<td>{escape(r.status)}</td>"
                    f"<td class='num'>{r.estimate_hours:.1f}</td>"
                    f"<td class='num rem'>{escape(rem_text)}</td>"
                    f"<td class='num'>{escape(sp_text)}</td></tr>"
                )
            body.append("</tbody></table>")
        body.append("</section>")

    body.append(
        '<p class="muted">Additional metrics (Jira hygiene score, ceremony effectiveness, …) '
        "are not calculated in this reporting mode yet.</p>"
    )

    title = escape(f"Sprint Report: {config.sprint_name}")
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="en"{data_theme_attr}>\n'
        "<head>\n"
        '<meta charset="utf-8" />\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        f"<title>{title}</title>\n"
        f"{css}\n"
        "</head>\n"
        "<body>\n"
        f"{''.join(body)}\n"
        f"{script}\n"
        "</body>\n"
        "</html>\n"
    )

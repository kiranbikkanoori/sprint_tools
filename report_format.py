"""
Generates the REPORT_FORMAT.md content — a field reference for the sprint report.

Called by:  sprint_report.py --generate-format
"""

from __future__ import annotations


def generate_report_format() -> str:
    return _FORMAT_TEXT


_FORMAT_TEXT = r"""# Sprint Report — Field Reference (story vs task worklog model)

This document describes the current sprint report. Regenerate after changes:

```
python sprint_report.py --generate-format -o ./output
```

**Code:** `report_generator.py` → `build_sprint_work_report()`, `generate_text_report()`  
**Chart:** `burndown_chart.py` → `generate_burndown_chart()` (stacked hours only; burndown line removed)

---

## Report Header

| Field | Source |
|-------|--------|
| Sprint name, duration label | `sprint_report_config.md` + Jira `start_date` / `end_date` |
| Report date | Config `report_date` or “today” |
| Sprint goal | Jira sprint `goal` |

---

## Logged Hours by Person — Stories / Tasks (non-story)

Two separate markdown tables with the same date columns:

1. **Stories** — Jira issue types **Story**, **User Story**, and **Epic** (case-insensitive), with no parent link (and not classified as Sub-task).
2. **Tasks (non-story)** — all other **non–sub-task** issue types (e.g. **Task**, **Bug**, **Spike**): log here, not on sub-tasks.

- **Included people:** Team members with **Include in Report = Yes** (name must match Jira worklog author).
- **Sub-task** worklogs do not appear in these tables (they appear under validation instead).
- **Dates:** Each table has one column per **weekday** from sprint start through `min(sprint_end, report_date)` (when `report_date` is set), plus a **total** column.
- **Team total row:** Last row sums hours **across all included people** for each day and for the row total.

**Mid-sprint:** If `report_date` in config is empty, the cut-off is **today**, so weekday columns and worklog filtering stop at `min(sprint_end, today)`.

---

## Weekdays With Zero Logged Hours (stories + tasks)

Weekdays in the report range where an included person logged **nothing on stories or tasks** (combined). Logging only on sub-tasks in that range still shows as a “missing” day for this section.

---

## Validation: Sub-tasks With Remaining Work

Sub-task issues (after config exclusions) with **remaining estimate** greater than zero. Requires `remaining_estimate_hours` (or raw) in the JSON — produced by `fetch_via_mcp.py` / `fetch_sprint_data.py`.

---

## Validation: Work Logged on Sub-tasks

Worklog entries on **Sub-task** issues whose **started** date falls in **[sprint_start, min(sprint_end, report_date)]**. Lists total hours and breakdown **by author** (all authors, not only included members).

---

## Planned vs Capacity

Per-included-person table (with a **Team total** row) summarising capacity, planned work, and logged work for the **full** sprint. Always uses the full sprint window — Report Date is ignored here, since this section is meant for end-of-sprint review.

| Column | Meaning |
|--------|---------|
| Work d | `sprint_duration_weeks × 5` (working days, same for everyone) |
| Mtg d | `meeting_days_reserved` from config (per person) |
| Leave d | Sum of `Planned Leaves` rows for the person |
| Other (h) | Sum of `Other Non-Development Activities` hours for the person |
| Eff. d | `max(0, Work d − Mtg d − Leave d)` |
| Capacity (h) | `max(0, Eff. d × 8 − Other (h))` |
| Planned (h) | Sum of `estimate_hours` for **Story / Task** issues whose `assignee` matches the person, after dropping `excluded_tickets`. Sub-tasks are not counted; parent stories are taken at face value (no replacement by sub-task estimates). `Extra Tickets` from config are **not** added. |
| Plan % | `Planned ÷ Capacity` (integer percent; `—` when Capacity is 0) |
| Logged (h) | Same total shown in the Stories + Tasks tables above, summed for the person |
| Util % | `Logged ÷ Capacity` (integer percent; `—` when Capacity is 0) |

---

## Sprint Completion & Velocity

Two related measures, computed for the **full sprint**:

- **Sprint Completion Rate** — fraction of **Stories + Tasks** (after dropping `excluded_tickets` and ignoring sub-tasks) considered done by sprint end. A ticket counts as done when its `status_category` is `Done` / `Complete`, **or** its `status` is `Resolved` (matches the Sprint Tickets table). Reported at both **ticket** and **story-point** granularity (target ≥ 90%).
- **Velocity (SP / person-day)** — `Σ story_points of done Stories+Tasks ÷ team effective person-days` (effective person-days come from the Planned vs Capacity table).

A **per-person** table follows the team summary, broken down by `assignee`. Unassigned tickets contribute to team totals only.

---

## Sprint Tickets — Status & Remaining Work

Per-ticket drilldown: every **Story / Task** in the sprint (sub-tasks excluded, `excluded_tickets` dropped), sorted **unfinished-first** then by status then by key, so leftover work appears at the top.

Columns: `Key`, `Summary` (truncated to ~60 chars), `Type`, `Assignee`, `Status`, `Estimate (h)`, `Remaining (h)`, `SP`.

Tickets whose status is `Resolved` are treated as effectively done and grouped with `Closed` (Jira's `status_category` for `Resolved` is still `In Progress`, but most workflows use `Resolved` as a final pre-close state).

A **⚠** marker on `Remaining (h)` flags tickets that are effectively done but still have `Remaining > 0` — a Jira-hygiene fix-up the team can clean up at sprint close.

---

## Other Metrics

Placeholder text only — burndown / remaining work, JIRA hygiene score, scope churn, etc. are **not** calculated in this mode.

---

## Chart PNG

- **File:** `sprint_burndown_<sprint>.png` (name unchanged for scripts).
- **Content:** Stacked bars = hours per **working day**, per **included** author, from worklogs on **Story + Task** keys only (same rules as the chart data in `sprint_report.py`).
- **Subtitle:** States that burndown / remaining work is under development.

---

## Config fields used today

| Field | Effect |
|-------|--------|
| Sprint Name | Matches Jira sprint |
| Report Date | Caps daily table, validation window, and chart |
| Team Members (Include Yes/No) | Who appears in hours table, gaps, and chart |
| Tickets to Exclude | Issues skipped entirely |
| Other config sections | Parsed but not used for metrics in this mode |

---

## JSON expectations

- `issues[]`: `key`, `type` (`Story` / `Task` / `Sub-task`), `issuetype_name`, `issuetype_subtask`, `has_subtasks`, `assignee`, `summary`, `parent_key`, optional `remaining_estimate_hours` / `remaining_estimate_raw`. Reports use `effective_issue_type()` so **refetch** after tool updates if `issuetype_name` was stuck on `Unknown`.
- `worklogs[key]`: `{ started, seconds, author }` for **every** sprint issue key (including stories, tasks, and sub-tasks)

""".lstrip()

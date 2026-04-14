"""
Generates the REPORT_FORMAT.md content — a field reference for the sprint report.

Called by:  sprint_report.py --generate-format
"""

from __future__ import annotations


def generate_report_format() -> str:
    return _FORMAT_TEXT


_FORMAT_TEXT = r"""# Sprint Report — Field Reference (parent worklog model)

This document describes the current sprint report. Regenerate after changes:

```
python sprint_report.py --generate-format -o ./output
```

**Code:** `report_generator.py` → `build_parent_work_report()`, `generate_text_report()`  
**Chart:** `burndown_chart.py` → `generate_burndown_chart()` (stacked hours only; burndown line removed)

---

## Report Header

| Field | Source |
|-------|--------|
| Sprint name, duration label | `sprint_report_config.md` + Jira `start_date` / `end_date` |
| Report date | Config `report_date` or “today” |
| Sprint goal | Jira sprint `goal` |

---

## Logged Hours by Person — Parent tasks / Standalone tasks

Two separate markdown tables with the same date columns:

1. **Parent tasks** — hours from worklogs on **Parent** issues only.
2. **Standalone tasks** — hours from worklogs on **Standalone** issues only.

- **Included people:** Team members with **Include in Report = Yes** (name must match Jira worklog author).
- **Sub-task** worklogs do not appear in these tables (they appear under validation instead).
- **Dates:** Each table has one column per **weekday** from sprint start through `min(sprint_end, report_date)` (when `report_date` is set), plus a **total** column.
- **Team total row:** Last row sums hours **across all included people** for each day and for the row total.

**Mid-sprint:** If `report_date` in config is empty, the cut-off is **today**, so weekday columns and worklog filtering stop at `min(sprint_end, today)`.

---

## Weekdays With Zero Logged Hours (parent + standalone)

Weekdays in the report range where an included person logged **nothing on parent or standalone** (combined). Logging only on sub-tasks in that range still shows as a “missing” day for this section.

---

## Validation: Sub-tasks With Remaining Work

Sub-task issues (after config exclusions) with **remaining estimate** greater than zero. Requires `remaining_estimate_hours` (or raw) in the JSON — produced by `fetch_via_mcp.py` / `fetch_sprint_data.py`.

---

## Validation: Work Logged on Sub-tasks

Worklog entries on **Sub-task** issues whose **started** date falls in **[sprint_start, min(sprint_end, report_date)]**. Lists total hours and breakdown **by author** (all authors, not only included members).

---

## Other Metrics

Placeholder text only — planned capacity, utilization, velocity, burndown, etc. are **not** calculated in this mode.

---

## Chart PNG

- **File:** `sprint_burndown_<sprint>.png` (name unchanged for scripts).
- **Content:** Stacked bars = hours per **working day**, per **included** author, from worklogs on **Parent + Standalone** keys only (same rules as the chart data in `sprint_report.py`).
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

- `issues[]`: `key`, `type` (`Parent` / `Sub-task` / `Standalone`), `assignee`, `summary`, `parent_key`, optional `remaining_estimate_hours` / `remaining_estimate_raw`
- `worklogs[key]`: `{ started, seconds, author }` for **every** sprint issue key (including parents and sub-tasks)

""".lstrip()

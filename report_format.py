"""
Generates the REPORT_FORMAT.md content — a field reference for the sprint report.

Called by:  sprint_report.py --generate-format
"""

from __future__ import annotations


def generate_report_format() -> str:
    return _FORMAT_TEXT


_FORMAT_TEXT = r"""# Sprint Report — Field Reference

This document describes every section and field in the generated sprint report.
Use it to understand how metrics are calculated, where data comes from, and how to
modify or extend the report.

**Generator code:** `report_generator.py` → `generate_text_report()`
**Cycle time code:** `report_generator.py` → `generate_cycle_time_section()`
**Burndown chart:** `burndown_chart.py` → `generate_burndown_chart()`

> **Regenerate this file** any time the report format changes:
> ```
> python sprint_report.py --generate-format -o ./output
> ```

---

## Report Header

| Field | Description | Source |
|-------|-------------|--------|
| Sprint Name | Name of the sprint | `sprint_report_config.md` → Sprint Name |
| Sprint Duration | Start and end dates, duration in weeks | Jira sprint data (`start_date`, `end_date`) + config (`sprint_duration_weeks`) |
| Report Date | Date the report was generated | Config `report_date`, defaults to today |
| Sprint Goal | Sprint goal text | Jira sprint `goal` field |
| Carried-over note | Count of tickets closed before sprint start | Detected automatically (see [Carried-Over Logic](#7-carried-over-closed-tickets-excluded)) |

---

## 1. Team Capacity

Shows each team member's available working capacity for the sprint.

| Column | Calculation | Source |
|--------|-------------|--------|
| Name | Team member display name | `sprint_report_config.md` → Team Members |
| Eff. Days | `working_days - meeting_days_reserved - leave_days` | Config + Jira sprint dates |
| Eff. Hours | `Eff. Days × 8 - other_exclusion_hours` | Derived |
| Leave | Planned leave days | `sprint_report_config.md` → Planned Leaves |
| Notes | Leave/exclusion details | Config |
| **TOTAL** | Sum of all Eff. Hours | Derived |

**Key formula:**
```
working_days = weekdays between sprint_start and sprint_end (inclusive)
effective_days = working_days - meeting_days_reserved - leave_days
capacity_hours = effective_days × 8 - other_exclusion_hours
```

**Config fields used:** `team_members`, `planned_leaves`, `other_exclusions`, `meeting_days_reserved`

---

## 2. Planned vs Logged Work

Compares each person's planned work against actual logged work.

| Column | Calculation | Source |
|--------|-------------|--------|
| Name | Team member | Config |
| Capacity | `capacity_hours` from Team Capacity | Derived |
| Planned | `max(0, estimate_hours - pre_sprint_logged_hours)` summed across all assigned tickets | Jira `timetracking.original_estimate` minus worklogs before sprint start |
| Logged | Sum of worklog hours within `[sprint_start, sprint_end]` for this person | Jira worklogs (`/rest/api/2/issue/{key}/worklog`) |
| Delta | `Logged - Planned` | Derived |
| Utilization | `Logged / Capacity × 100` | Derived |

**Key formula:**
```
planned_per_ticket = max(0, estimate_hours - pre_sprint_logged_hours)
total_planned = sum(planned_per_ticket) for all assigned tickets
utilization = total_logged / capacity_hours × 100%
```

**Notes:**
- `pre_sprint_logged_hours` = sum of worklog hours where `wl.started < sprint_start`
- Only worklogs authored by included team members count toward `Logged`
- Parent tickets are excluded if `exclude_parent_estimates` is set in config

---

## 3. Per-Ticket Worklog Details

Detailed breakdown of every ticket assigned to each person (toggled by `show_per_ticket_details` in config).

| Column | Calculation | Source |
|--------|-------------|--------|
| Ticket | Jira issue key | Jira issue `key` |
| Status | Current Jira status name | Jira `status.name` |
| Estimate | Original time estimate | Jira `timetracking.original_estimate` |
| Planned | `max(0, estimate - pre_sprint_logged)` | Derived |
| Logged | In-sprint logged hours for this ticket | Jira worklogs within sprint dates |
| Delta | `Logged - Planned` (positive = over, negative = under) | Derived |
| Summary | First 50 chars of issue summary | Jira `summary` |

**Notes:**
- Tickets with 0h logged but >0h planned are highlighted in **bold**
- Tickets sorted by key within each person

---

## 4. Ticket Status Distribution

Counts tickets by their current Jira status.

| Field | Calculation | Source |
|-------|-------------|--------|
| Status | Jira status name (e.g., "Open", "In Progress", "Closed") | Jira `status.name` |
| Count | Number of active sprint tickets in that status | Derived |
| Completion | `closed / total` and `(closed + in_review) / total` | `status_category == "Done"` for closed; status name contains "review" for in-review |

---

## 5. Daily Log Gaps

Shows working days where a team member logged zero hours (toggled by `show_daily_log_gaps` in config).

| Column | Calculation | Source |
|--------|-------------|--------|
| Name | Team member | Config |
| Missing Days | Count of working days with 0h logged | Jira worklogs vs working days calendar |
| Dates | List of specific dates with no logged work | Derived |

**Notes:**
- Only counts Mon–Fri working days within the sprint window
- Useful for identifying worklog compliance issues

---

## 6. Sprint Completion & Velocity

### 6a. Sprint Completion Rate

| Field | Calculation | Target |
|-------|-------------|--------|
| Completed / Committed | Tickets with `status_category == "Done"` / total active tickets | ≥ 90% |
| Completed + In Review | `(Done + In Review) / total` | — |
| Status | `ON TRACK` (≥90%), `AT RISK` (70–89%), `BEHIND` (<70%) | — |

**Notes:**
- Only active sprint tickets count (carried-over closed tickets are excluded)
- "In Review" = any ticket whose status name contains "review" (case-insensitive)

### 6b. Sprint Velocity

| Field | Calculation | Source |
|-------|-------------|--------|
| Story Points committed | Sum of `story_points` for all active tickets | Jira `customfield_10344` |
| Story Points completed | Sum of `story_points` for tickets with `status_category == "Done"` | Same field, filtered by status |
| Team man-days available | Sum of `capacity_days` for all included members | Derived from Team Capacity |
| **Velocity** | `SP completed / man-days available` | Derived |

**Fallback:** If no tickets have story points, velocity uses estimated hours instead:
```
Velocity = estimated_hours_of_completed_tickets / team_man_days
```

**Key distinction:** Story points completed = story points of **closed tickets only** (not based on logged hours). A 2 SP ticket that took 5 days of actual work still counts as 2 SP completed.

### 6c. Velocity by Team Member

Same calculation as team velocity, broken down per person:

| Column | Calculation |
|--------|-------------|
| Person | Team member name |
| Man-days | Person's `capacity_days` |
| SP Committed | Sum of `story_points` across their assigned tickets |
| SP Completed | Sum of `story_points` for their "Done" tickets |
| Velocity (SP/day) | `SP Completed / Man-days` |
| Completion | `Done tickets / Total tickets (%)` |

---

## 7. Carried-Over Closed Tickets (Excluded)

Lists tickets that were closed **before the sprint started** and are excluded from all calculations.

| Column | Source |
|--------|--------|
| Ticket | Jira issue key |
| Assignee | Jira assignee |
| Estimate | Jira `timetracking.original_estimate` |
| Summary | First 55 chars of issue summary |

**Detection logic (in order):**
1. If `resolution_date` exists and is before `sprint_start` → excluded
2. Fallback: if status is "Done"/"Closed" AND zero in-sprint worklogs AND has pre-sprint worklogs → excluded

**Impact:** These tickets are completely removed from:
- Planned vs Logged Work
- Per-Ticket Details
- Status Distribution
- Sprint Completion Rate
- Sprint Velocity
- Burndown Chart
- Daily Log Gaps

---

## 8. Sprint Health Summary

A consolidated view of key sprint health indicators.

| Metric | Calculation |
|--------|-------------|
| Team utilization | `total_logged / total_capacity × 100%` |
| Plan adherence | `total_logged / total_planned × 100%` |
| Sprint completion rate | Same as section 6a |
| Sprint velocity | Same as section 6b |
| Carried-over closed | Count of excluded pre-sprint tickets |
| Tickets closed | `Done / total active tickets (%)` |
| Tickets closed+review | `(Done + In Review) / total (%)` |
| Unstarted (with planned hours) | Tickets with `planned_hours > 0` but `in_sprint_logged == 0` |
| Overcommitted members | Members where `total_planned > capacity × 1.05` |

---

## 9. PR Cycle Time (optional)

Generated from GitHub PR data via `cycle_time_report.py`. Requires the GitHub CLI (`gh`) to be installed and authenticated. If `gh` is not available, this section displays a note that cycle time data is unavailable — all other report sections work normally.

To suppress the note entirely, use `--skip-cycle-time`.

Appended to the main report when `--cycle-time-data` is provided and the data file exists.

### 9a. Cycle Time by Team Member

| Column | Calculation | Source |
|--------|-------------|--------|
| Person | PR author (mapped from GitHub username) | GitHub API |
| PRs | Count of PRs for this person | GitHub API |
| Avg Coding | Average: first commit → PR creation | `gh pr` commits + creation date |
| Avg Pickup | Average: PR creation → first human review | GitHub reviews timeline |
| Avg Review | Average: first human review → merge | GitHub reviews + merge date |
| Avg Cycle | Average: first commit → merge | End-to-end |

**Time calculation:**
- All times are **business hours** (weekends Mon–Fri only, Sat/Sun excluded)
- `business_hours_between(start, end)` counts only hours on weekdays

### 9b. PR Details by Person

| Column | Source |
|--------|--------|
| PR | GitHub PR number + link |
| Jira | Jira ticket key extracted from PR branch name |
| State | merged / open / closed |
| Coding | First commit timestamp → PR created_at |
| Pickup | PR created_at → first human review timestamp |
| Review | First human review → merged_at |
| Cycle | First commit → merged_at |
| Size | Lines added / deleted |
| Commits | Total commit count |
| Reviews | Count of human reviews (excludes bot reviews) |

### 9c. Cycle Time Insights

| Insight | Calculation |
|---------|-------------|
| Fastest merge | PR with minimum `cycle_time_hours` among merged PRs |
| Slowest merge | PR with maximum `cycle_time_hours` among merged PRs |
| Biggest bottleneck | Whichever of Coding/Pickup/Review has the highest team average |
| Open PRs awaiting review/merge | PRs with state "OPEN", showing age and review status |

---

## 10. Burndown Chart (PNG)

Two-panel chart saved as `sprint_burndown_{name}.png`.

### Top Panel: Remaining Work Burndown

| Element | Calculation |
|---------|-------------|
| Ideal Burndown (dashed line) | Linear from `total_planned_hours` to 0 across working days |
| Actual Remaining (solid line) | `total_planned - cumulative_logged` per working day |
| Today marker | Vertical line at the report date |
| X-axis | Working days only (Mon–Fri), weekends skipped |

### Bottom Panel: Daily Hours Logged (stacked bars)

| Element | Calculation |
|---------|-------------|
| Stacked bars | Per-member logged hours on each working day |
| Ideal rate (dashed line) | `total_planned_hours / number_of_working_days` |
| Member colours | Assigned in order from config, colour-blind-friendly palette |

**Data source:** Jira worklogs filtered to sprint date range, included team members only. Carried-over ticket worklogs are excluded.

---

## Data Flow Overview

```
Jira MCP Server ──→ fetch_via_mcp.py ──→ sprint_data_*.json ─┐
                                                               │
GitHub (gh CLI) ──→ cycle_time_report.py ──→ cycle_time_data_*.json
                                                               │
sprint_report_config.md ───────────────────────────────────────┤
                                                               │
                                                               ▼
                                                      sprint_report.py
                                                       (orchestrator)
                                                         │       │
                                                         ▼       ▼
                                                report_generator  burndown_chart
                                                      .py              .py
                                                         │       │
                                                         ▼       ▼
                                              sprint_report_*.md  sprint_burndown_*.png
```

---

## Configuration Reference

All report behaviour is controlled by `sprint_report_config.md`. Key fields:

| Config Field | Affects Sections | Description |
|-------------|------------------|-------------|
| `Sprint Name` | All | Identifies the sprint in Jira |
| `Sprint Duration` | Header, Capacity | Duration in weeks |
| `Report Date` | Header, Burndown | Cut-off date for data |
| `Team Members` | All | List of `Name (included/excluded)` |
| `Planned Leaves` | Capacity | `Name: Xd` |
| `Other Exclusions` | Capacity | `Name: Xh` for non-sprint work |
| `Meeting Days Reserved` | Capacity | Days per person reserved for ceremonies |
| `Excluded Tickets` | All | Ticket keys to skip entirely |
| `Exclude Parent Estimates` | Planned vs Logged, Velocity | Whether parent issues count |
| `Show Per-Ticket Details` | Per-Ticket Details | Toggle section on/off |
| `Show Daily Log Gaps` | Daily Log Gaps | Toggle section on/off |
| `GitHub Repo` | PR Cycle Time | Repo identifier for `gh` CLI |
| `Generate PR cycle time report` | PR Cycle Time | Toggle cycle time analysis |

---

## How to Extend the Report

### Adding a new field to an existing section

1. If the data comes from Jira, update `fetch_via_mcp.py`:
   - Add the field to the `fields` parameter in `jira_get_sprint_issues` call
   - Extract it in `convert_issue()`
2. Add the field to `TicketReport` dataclass in `report_generator.py`
3. Populate it in `build_person_reports()`
4. Display it in `generate_text_report()` at the desired location
5. **Update this doc:** run `python sprint_report.py --generate-format` and update `_FORMAT_TEXT` in `report_format.py`

### Adding a new section

1. Add a new block in `generate_text_report()` (follow the pattern of existing sections)
2. If it needs config toggles, add the field to `config_parser.py` → `SprintConfig`
3. Update `sprint_report_config.md` with the new option
4. Update the format text in `report_format.py`

### Adding a new data source

1. Create a new fetch script (similar to `cycle_time_report.py`)
2. Have it output a JSON file
3. Pass the JSON path as an argument to `sprint_report.py`
4. Load and integrate in `generate_text_report()` or as a separate `generate_*_section()` function

### Jira custom fields

Use the MCP tool `jira_search_fields` to find the correct `customfield_XXXXX` ID:
```bash
# Via the MCP client in fetch_via_mcp.py:
client.call_tool('jira_search_fields', {'keyword': 'your field name', 'limit': 10})
```

The current story points field for this Jira instance is **`customfield_10344`** (returns `{"value": X}`).
""".lstrip()

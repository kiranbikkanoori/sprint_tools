# Sprint Report Configuration

Fill in the sections below before running `run.sh` or `sprint_report.py`. The **current** markdown report focuses on **parent/standalone worklogs**, validation for **sub-tasks**, and **daily hours** tables; see **Report tool — features under development** for what is not implemented yet.

---

## Report tool — features under development

These capabilities are **not** implemented in the current report generator (or only stubbed). They may be added back as the **parent-task logging** model stabilizes.


| #   | Feature                                                                                                    | Status                                                                                     |
| --- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| 1   | Burndown / remaining work (ideal vs actual line chart)                                                     | Chart PNG is **stacked hours per day** only; subtitle notes burndown is TBD                |
| 2   | Team capacity table (meeting reserve, leave, exclusions → hours)                                           | Config fields exist below; **not** used in the generated report yet                        |
| 3   | Planned vs logged, utilization, delta vs capacity                                                          | **Not** generated                                                                          |
| 4   | Per-ticket worklog detail tables (estimate, remaining, delta)                                              | **Not** generated                                                                          |
| 5   | Ticket status distribution & completion %                                                                  | **Not** generated                                                                          |
| 6   | Sprint velocity & story-point / hours velocity                                                             | **Not** generated                                                                          |
| 7   | Sprint health summary (aggregate KPIs)                                                                     | **Not** generated                                                                          |
| 8   | Carried-over closed tickets section                                                                        | **Not** generated                                                                          |
| 9   | **Extra Tickets** (table below)                                                                            | Parsed from config; **not** merged into Jira fetch or report yet                           |
| 10  | Report toggles: *Exclude parent story estimates*, *Show per-ticket worklog details*, *Show daily log gaps* | Parsed but **ignored**; weekday gap table is **always** shown (parent+standalone combined) |


---

## Sprint Details

- **Sprint Name**: `Wi-Fi_LMAC_2026_7`
- **Sprint Duration (weeks)**: `2`

---

## Team Members

List all active sprint members below. Remove or comment out anyone who should be excluded (e.g., managers doing only design discussions).


| #   | Name                | Role      | Include in Report |
| --- | ------------------- | --------- | ----------------- |
| 1   | Sunil Jangiti       | Developer | Yes               |
| 2   | Hemanth Reddy Narra | Developer | Yes               |
| 3   | Shivam Patil        | Developer | Yes               |
| 4   | Kiran Bikkanoori    | Developer | Yes               |
| 5   | Ashwini Kumar       | Developer | Yes               |
| 6   | Ritesh Seemakurty   | Developer | Yes               |
| 7   | Trinadh Angara      | Manager   | No                |


---

## Capacity Adjustments

### Time Reserved for Meetings/Ceremonies (per person per sprint)

- **Days reserved**: `1`

> This is deducted from each person's capacity. For a 2-week sprint with 1d reserved, effective capacity = 9d (72h) per person.

### Planned Leaves


| Name             | Leave Days | Notes |
| ---------------- | ---------- | ----- |
| Kiran Bikkanoori | 3          |       |
|                  |            |       |
|                  |            |       |


### Other Non-Development Activities (per person)

Use this to account for any recurring non-sprint work (support tickets, production issues, mentoring, etc.) that reduces available capacity.


| Name | Hours Excluded | Reason |
| ---- | -------------- | ------ |
|      |                |        |
|      |                |        |


---

## Extra Tickets

Tickets outside the sprint that should still be included in the report (e.g., tickets from another sprint or backlog that the team is actively working on).


| Ticket Key | Assignee | Notes |
| ---------- | -------- | ----- |
|            |          |       |
|            |          |       |


---

## Tickets to Exclude

Tickets in the sprint that should NOT be counted (e.g., tracking/umbrella tickets without real work).


| Ticket Key | Reason |
| ---------- | ------ |
|            |        |
|            |        |


---

## Report Options

- **Report Date** (calculate logged work up to this date, leave blank for today): ``
- **Exclude parent story estimates** (avoid double-counting with sub-tasks): `Yes` — *under development; see table above*
- **Show per-ticket worklog details**: `Yes` — *under development*
- **Show daily log gaps** (flag people who haven't logged work on a given day): `Yes` — *under development; gap table is always on for parent+standalone*

> Only **Report Date** affects the current tool; the other three options are kept for when those features return.

---

## Sprint Metrics Definitions

The report automatically calculates the following metrics:

### Sprint Completion Rate


| Field           | Value                                                          |
| --------------- | -------------------------------------------------------------- |
| **Definition**  | % of committed sprint backlog items completed by end of sprint |
| **Target**      | ≥ 90%                                                          |
| **Measured by** | Scrum Master                                                   |
| **How**         | Tickets with status category "Done" / Total committed tickets  |


### Sprint Velocity and Consistency


| Field           | Value                                                         |
| --------------- | ------------------------------------------------------------- |
| **Definition**  | Story points (or estimated hours) per sprint per man-day      |
| **Target**      | Trend line should show 10% improvement in a cycle             |
| **Measured by** | Scrum Master                                                  |
| **How**         | Total completed story points (or hours) / Total team man-days |


> **Note:** If story points are configured on Jira tickets, velocity uses story points.
> Otherwise, it falls back to estimated hours of completed items.
> Velocity consistency (cross-sprint comparison) requires data from multiple sprints (TBD).

---

> **Usage instructions:** See `README.md` for setup, prerequisites, and how to run the tools.


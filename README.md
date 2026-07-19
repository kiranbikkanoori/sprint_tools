<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="Sprint Report desktop app that turns a Jira sprint into a markdown report and burndown chart in four guided steps">
</p>

# Sprint Report

Desktop app for sprint leads: connect to Jira, pick a sprint, adjust capacity, and generate a markdown report plus hours chart — previewed inside the app.

**Files produced**

| File | What it is |
|------|------------|
| `sprint_report_<sprint>.md` | The full report (all tables below) |
| `sprint_burndown_<sprint>.png` | Stacked daily hours by person |

---

<p align="center">
  <img src="./assets/readme/section-howto.svg" width="100%" alt="How to use the Sprint Report app">
</p>

<p align="center">
  <img src="./assets/readme/workflow.svg" width="100%" alt="Four-step workflow: Settings, Sprint, Configure, Generate">
</p>

### Steps

| Step | You do | App does |
|------|--------|----------|
| **1. Settings** | Enter Jira URL + Personal Access Token (or username/password) | Saves credentials encrypted locally |
| **2. Sprint** | Search a board, pick a sprint, click *Load sprint* | Fetches issues + worklogs in the background |
| **3. Configure** | Set report date, include/exclude people, leaves, exclusions | Auto-fills assignees; remembers config per sprint |
| **4. Generate** | Click Generate | Builds report + chart, previews both, opens the output folder |

### Quick checklist

1. **Settings** → Jira URL + PAT → Save  
2. **Sprint** → pick board + sprint → *Load sprint*  
3. **Configure** → set **report date**, uncheck people who should not appear, add leaves/exclusions  
4. **Generate** → preview → open output folder  

### Configure tips (important)

**Report date** — the report and chart only include worklogs **up to and including** this date. Use today for a mid-sprint snapshot, or the sprint end date for a final report. A wrong date truncates hours, KPIs, and the chart.

**Planned leaves** — the person name must match a **Team members** row exactly (same spelling/spacing). Prefer the dropdown. If the name does not match, that leave is ignored and capacity stays wrong.

**Include checkbox** — only included people appear in hours tables, completion, and the chart. Worklogs are matched by **Jira worklog author** name.

**Excluded tickets** — dropped from KPIs, completion, and the tickets table (umbrellas/duplicates).

---

<p align="center">
  <img src="./assets/readme/section-outcomes.svg" width="100%" alt="What you get from Sprint Report">
</p>

Below is every table (and the chart) the tool generates, in report order, with a small layout sketch of each.

### 1. Logged Hours by Person — Stories

**Purpose:** See who logged time on **Story / User Story / Epic** work each weekday.

**Columns:** Person → one column per weekday through the report date → **Total (stories)**  
**Rows:** Each included person, then a **Team total** row.  
**Cells:** Daily hours; when per-ticket detail is on, issue keys appear under the day total.  
**Note:** Sub-task worklogs are not counted here.

<p align="center">
  <img src="./assets/readme/table-hours.svg" width="100%" alt="Diagram of the logged hours table with people, weekdays, and team total">
</p>

### 2. Logged Hours by Person — Tasks (non-story)

**Purpose:** Same layout as Stories, but for **Task / Bug / Spike** and other non-story, non-sub-task types.

**Columns / rows:** Same shape as the Stories table; total column is **Total (tasks)**.  
**Use it for:** Separating story delivery time from other ticket types.

<p align="center">
  <img src="./assets/readme/table-hours.svg" width="100%" alt="Tasks hours table uses the same layout as the Stories table">
</p>

### 3. Sprint KPI Summary

**Purpose:** One sprint-level scorecard after the hours tables.

**Columns:** KPI | Value | Notes  

| KPI row | Meaning |
|---------|---------|
| Sprint completion rate | Done Stories+Tasks / accepted Stories+Tasks |
| Sprint velocity | Story points delivered / effective person-days |
| Scope stability & backlog churn | Count of Stories+Tasks added after sprint start |
| Number of tickets / completed / differed | Committed, done, and remaining counts |
| Participation, ceremony, hygiene, … | Shown as `N/A` until implemented |

<p align="center">
  <img src="./assets/readme/table-kpi.svg" width="100%" alt="Diagram of the Sprint KPI Summary table">
</p>

### 4. Tickets Added After Sprint Start

**Purpose:** Drill into backlog churn. **Only appears when churn is non-zero.**

**Columns:** Key | Summary | Assignee | Status | Sprint Started (IST) | Added To Sprint (IST)

<p align="center">
  <img src="./assets/readme/table-churn.svg" width="100%" alt="Diagram of the backlog churn ticket list">
</p>

### 5. Validation: Sub-tasks With Remaining Work

**Purpose:** Hygiene check — child tickets that still have remaining estimate.

**Columns:** Ticket | Assignee | Parent | Remaining | Summary  
**Good result:** Empty (“No sub-tasks with non-zero remaining estimate”).

### 6. Validation: Work Logged on Sub-tasks

**Purpose:** Hygiene check — hours logged on sub-tasks in the report window (team should usually log on stories/tasks).

**Columns:** Ticket | Assignee | Parent | Total (h) | By author | Summary  
**Good result:** Empty.

<p align="center">
  <img src="./assets/readme/table-validation.svg" width="100%" alt="Diagram of the sub-task validation tables">
</p>

### 7. Sprint Completion & Velocity

**Purpose:** End-of-sprint delivery quality and throughput.

**Team table columns:** Metric | Value | Target — tickets/SP committed & done, completion %, effective person-days, velocity.  
**Per-person table columns:** Person | Tickets done/committed | Tickets % | SP delivered/committed | SP % | SP / person-day  

A ticket counts as done when status category is Done/Complete **or** status is Resolved.  
Effective person-days = sprint weeks × 5 − meeting reserve − planned leaves (for included people).

<p align="center">
  <img src="./assets/readme/table-completion.svg" width="100%" alt="Diagram of team and per-person completion and velocity tables">
</p>

### 8. Sprint Tickets — Status & Remaining Work

**Purpose:** Leftover and hygiene view of every Story/Task in the sprint (excluded tickets omitted).

**Columns:** Key | Summary | Type | Assignee | Status | Estimate (h) | Remaining (h) | SP  
**Sort:** Unfinished first, then status, then key.  
**⚠ marker:** Ticket looks done/Resolved but Remaining is still greater than zero.

<p align="center">
  <img src="./assets/readme/table-tickets.svg" width="100%" alt="Diagram of the sprint tickets status and remaining work table">
</p>

### 9. Other Metrics

Placeholder only — not calculated yet (called out in the report so the gap is visible).

### 10. Burndown chart (PNG)

**Purpose:** Visual of hours logged per working day, stacked by included person (Story + Task worklogs through the report date).

**Not yet:** A remaining-work burndown line (subtitle in the chart notes this).

<p align="center">
  <img src="./assets/readme/proof-burndown.png" width="100%" alt="Example stacked hours chart for Wi-Fi_LMAC_2026_11">
</p>

---

### Who and what is included

| Rule | Effect |
|------|--------|
| Include = Yes | Person appears in hours, completion, and chart |
| Worklog author name | Must match the team member name used in the report |
| Excluded tickets | Omitted from KPIs, completion, and ticket list |
| Report date | Caps weekday columns, validation window, and chart |
| Sub-tasks | Not in hours/completion/ticket tables; only in validation sections |

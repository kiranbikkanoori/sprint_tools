# Ticket status across sprints — how the tool behaves today

Short answers to “what will the report show?” when tickets move teams/sprints or get closed later.

## Core rule

**Closed / open in the report = current Jira status when you click Generate.**

It does **not** freeze status at sprint end. There is no “as of sprint close” snapshot.

Done check (same for KPI completion and the tickets table):

- `status_category` is `Done` or `Complete`, **or**
- `status` is `Resolved`

Source: `report_generator.build_ticket_rows` / `build_completion_velocity`.

Issue list comes from Jira Agile `GET /rest/agile/1.0/sprint/{id}/issue` — issues Jira still associates with that sprint — then each issue’s **live** `status` / `statusCategory` fields are read.

---

## Scenario A — Ticket hops teams mid-sprint

Example:

1. Team A accepts ticket in Sprint A1 (2 weeks).
2. Mid-sprint, ticket moves to Team B’s Sprint B1.
3. Mid-sprint again, moves to Team C.
4. Later the ticket is closed.
5. You run this tool on **Team A / Sprint A1**.

### Will it appear at all?

| Case | Usually |
|------|---------|
| Sprint A1 was **closed** and Jira kept A1 on the Sprint field history | Ticket often **still appears** in Sprint A1’s issue list |
| Ticket was **removed** from an **open** Sprint A1 (only current sprint left on the field) | Ticket may **disappear** from A1’s API list |

So membership is “does Jira still list this issue under that sprint?”, not “was it assigned to Team A at some point in the past week.”

### Closed or pending on that report?

Whatever status it has **now**:

| When you run the report | Status column / completion |
|-------------------------|----------------------------|
| Ticket still open (anywhere) | Shows **not done** (Open / In Progress / Blocked / …) |
| Ticket already closed/Resolved | Shows **done** — even for Sprint A1 |

So: for Team A’s first sprint, at the time the ticket was closed elsewhere, a re-run of A1 will typically show it as **closed/done**, not “still pending for A1,” if the issue is still in A1’s sprint issue list.

Mid-sprint hours on A1 still depend on worklogs dated in A1’s weekday window by included authors — that part is date-based, not status-based.

---

## Scenario B — Open at sprint end, closed later; re-run first sprint

| When you run | What the report shows for that ticket |
|--------------|----------------------------------------|
| At/near end of Sprint 1, ticket still open | **Not closed** — unfinished, hurts completion % |
| A few sprints later, ticket now Closed/Resolved; you re-generate Sprint 1 | **Closed / done** — completion % improves vs the earlier run |

Same ticket, same historical sprint, **different report results** depending on when you generate. The tool is a live view, not an archive of “what Sprint 1 looked like on close day.”

---

## What the tool does track historically

| Field | Historical? |
|-------|-------------|
| Status / done vs open | **No** — live |
| Assignee, remaining estimate, SP | **No** — live |
| Worklogs in sprint date window | **Yes** — by `started` date |
| Added after sprint start (churn) | **Yes** — from changelog |
| Sprint membership list | **Mostly** current association via sprint issues API (+ Jira’s sprint field history quirks) |

---

## Implication for redesign / later work

If you need “Sprint 1 as of close”:

1. Generate and **archive** the MD/HTML at sprint end, or
2. Later: resolve status from changelog as of `sprint.end_date` (not built today).

Until then: treat re-runs of old sprints as **current-state overlays** on that sprint’s issue set.

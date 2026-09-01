# Sprint report page redesign — locked decisions

Build checklist for the **in-app Generate report surface** (native tabs).  
MD/HTML exports stay for sharing; they do **not** have to mirror tab layout 1:1.

| Artifact | Path |
|----------|------|
| This brief | `docs/design/report-page-redesign.md` |
| Canvas backup (old mockups) | `docs/design/report-page-redesign.canvas.tsx` |
| Status / re-run caveat | `docs/design/ticket-status-across-sprints.md` |
| App shell capsules | `docs/design/app-shell-redesign.md` |

**Help** stays a **separate app tab** (not inside Generate).  
**No bar charts** in the Generate UI.

---

## Problem

Generate today loads the export into `QTextBrowser`. Wide tables are hard to use; there is no jump/filter/drill-down. Rebuild Generate as a native review UI fed by structured report data (not by re-parsing HTML).

---

## Personas

| Persona | Primary path after Generate |
|---------|----------------------------|
| **Scrum master / presenter** | Fix-ups (if any) → Overview → Hours |
| **Developer** | Hours → Tickets |

**Default tab after Generate:** **Fix-ups** if alert count &gt; 0, else **Overview**.

---

## Tabs (locked)

| Tab | Single-sentence job |
|-----|---------------------|
| **Overview** | “Director/SM: is this sprint OK to present?” |
| **Hours** | “Who logged what, what’s still assigned, vs capacity — and who logged on sub-tasks?” |
| **Fix-ups** | “What needs a human action before we call the sprint clean?” (exceptions only) |
| **Tickets** | “Full Story/Task inventory — filter, sort, find a key.” |
| **KPIs** | “Familiar export tables: Sprint KPI Summary + Completion & Velocity.” |

Actions on the page (all tabs): **Open HTML** · **Reveal folder**.

---

### 1. Overview

**Keep.** SM/director scorecard only — not a copy of the whole report.

**Chips (no N/A rows):**

- Completion (tickets %)
- Completion (SP %)
- Velocity (SP / person-day)
- Open tickets count
- Churn count
- Team Remaining (h)
- Team Capacity (h)

**Also:**

- Live-status banner (always): *Status and remaining are as of this generate run, not frozen at sprint end.*
- Sprint goal: **full text**, in a **scrollable box under the chips** (chips stay above the fold; box max ~30% height).
- Optional one-liner: “N fix-ups → open Fix-ups” (count only; no duplicate lists).

**Do not put on Overview:** full KPI table with N/As, full completion tables, hours matrix, ticket grids, charts. Those live on the **KPIs** tab.

---

### 1b. KPIs

**Keep.** Familiar SM scorecard tables from the MD/HTML export:

1. **Sprint KPI Summary** — `KPI | Value | Notes` (including N/A rows)
2. **Sprint Completion & Velocity** — Team metrics + Per-person table


### 2. Hours

**In-app: Combined view only** (no Stories | Tasks mode toggles).

**Export (MD/HTML):** keep separate Stories / Tasks tables + Remaining column as today (sharing/print).

**Combined matrix columns:**

- Person
- Weekday columns through report date
- **Logged (h)** (total)
- **Remaining (h)** — one column = Story + Task remaining for that assignee
- **Capacity (h)** — full sprint: `(work days − meeting − leave) × 8 − other exclusions`

**Per day cell (option B):** show total plus three color-coded mini values:

| Code | Meaning | Color intent |
|------|---------|--------------|
| **S** | Story worklogs | Distinct “story” color |
| **T** | Task / Bug / other non-story, non-sub-task | Distinct “task” color |
| **✗** | Sub-task worklogs (not allowed) | Warning / “shouldn’t log here” color |

Legend visible on the tab. Day cells show ticket chips as `KEY (Xh)`; no side drawer. Below the matrix: **Missing weekdays** (Person | days with 0h story+task; leave exclusion later).

**Sub-task hours:** shown in Combined (**✗**) **and** listed under Fix-ups (A).

---

### 3. Fix-ups (renamed from “Alerts”)

**Exceptions / action queue only** — not the full unfinished backlog.

Section header includes **Sprint started (IST)** once; Churn rows include **Added to sprint (IST)**.

**Include only:**

1. Mid-sprint adds (**Churn**)
2. Done/Resolved with remaining **⚠**
3. Sub-tasks with remaining estimate
4. Sub-task worklogs in the report window

**Do not** duplicate the general “all open tickets” list here — that lives on **Tickets**.

**Overlap with Tickets is OK:** a ⚠ or churn Story/Task appears in Fix-ups (action) **and** still in Tickets (inventory). Sub-tasks appear in Fix-ups only (Tickets stays Stories/Tasks).

**Empty state:** “No fix-ups — sprint looks clean” + links/shortcuts to Overview / Hours / Tickets.

**Unified table columns:**

| Column | Content |
|--------|---------|
| Severity | High / Med / Low |
| Type | Churn · ⚠ Remaining · Sub-task remaining · Sub-task worklog |
| Key | Issue key |
| Person | Assignee / author as relevant |
| Summary | Short text |
| Why / what to do | One-line guidance |

**Severity guide:**

- Churn + ticket still not done → **High**; churn on already-done → **Low**
- ⚠ Remaining → **Med**
- Sub-task remaining / sub-task worklog → **Med**

---

### 4. Tickets

Full Story/Task list (excluded tickets dropped).

**Default:** not-done first (same idea as current export sort), then status, then key.

**v1 filters:** Status · Assignee · ⚠ only · Type (Story / Task).

**Note:** same live-status caveat as Overview (short line OK).

---

## App shell (related, not Generate tabs)

- Capsule workflow: Settings · Sprint · Configure · Generate  
- Help remains separate  
- Same capsule language for Generate section tabs: Overview · Hours · Fix-ups · Tickets · KPIs

---

## Implementation order (suggested)

1. Structured data from `report_generator` → GUI (no HTML round-trip)
2. Overview chips + banner + scrollable goal + default-tab rule  
3. Fix-ups table + empty state  
4. Tickets table + filters  
5. Hours Combined matrix (S/T/✗ + Remaining + Capacity; chips with hours; missing-weekdays table)  
6. Capsule chrome polish  

---

## Multi-team presenter pack (v1)

Sprint owns the pack:

- Primary action **Add sprint** (first member and every later one).
- Pack list on Sprint (remove; order = add order). Same board+sprint replaces.
- Configure edits one active member at a time (pack combo); Generate runs the whole pack.
- Each Generate tab stacks **header band** (`board · sprint`) + that team’s existing widgets.
- Separate tables only — no mega-table Sprint column, **no org rollup totals**.
- Export: one MD/HTML set **per slot** (existing naming). Combined director HTML / SUMMARY later.

## Explicit non-goals (this redesign)

- Combined multi-team HTML/MD or SUMMARY rollup (later)
- Org-level chips / totals
- Point-in-time status as of sprint end (document caveat only for now)
- Bar charts / Chart tab
- In-app Stories | Tasks mode toggles (export keeps two tables)
- Saved named packs / drag reorder / PPT export

---

## Grill outcomes (decision log)

| Q | Choice |
|---|--------|
| Overview exists? | Yes — SM scorecard |
| Overview job | Director/SM: OK to present? |
| Capacity | On Hours (Logged / Remaining / Capacity) |
| Fix-ups vs Tickets | Fix-ups = selected exceptions; Tickets = full list |
| Default tab | Fix-ups if any, else Overview |
| Hours modes | Combined only in-app |
| Day cell | Total + S \| T \| ✗ color mini values |
| Sub-task hours | Hours + Fix-ups |
| Remaining | One combined column |
| Overview goal | Full text, scrollable under chips |
| Tab name | **Fix-ups** (not Alerts) |
| Tickets default | Not done first |
| Tickets filters v1 | Status, Assignee, ⚠, Type |

When implementing, treat this file as source of truth over older canvas mockups (Hybrid “Alerts” / Chart / Stories-Tasks toggles are superseded).

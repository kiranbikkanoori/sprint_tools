# Sprint report page redesign

Saved so this work survives even if the Cursor canvas viewer stops opening.

| Artifact | Path |
|----------|------|
| Design brief (this file) | `docs/design/report-page-redesign.md` |
| Canvas source (backup) | `docs/design/report-page-redesign.canvas.tsx` |
| Live Cursor canvas (when available) | `~/.cursor/projects/home-kibikkan-sprint-tools/canvases/report-page-redesign.canvas.tsx` |

**Sample data used:** `output/sprint_report_Wi-Fi_LMAC_2026_11.md`  
**Current UI:** Generate page loads exported HTML into `QTextBrowser` (`gui/pages/generate_page.py`).

---

## Problem

The Generate page treats the export file as the UI.

- Wide hours tables are hard to scan in `QTextBrowser`
- Theme toggle / JS is stripped in-app
- MD fallback is raw text
- No section jump, filter, sort, or drill-down
- Validation / hygiene / churn are buried mid-document

MD + HTML exports should stay for sharing. The **in-app page** should become a native review surface.

---

## Concepts

### Today — document preview

One long HTML/MD scroll. Same content as the file; no navigation.

### A — Sprint briefing

- KPI hero first (completion, SP %, velocity, churn)
- Deep tables behind tabs: Overview · Hours · Validation · Tickets
- **No bar charts** — numbers and tables only

**Strength:** Matches end-of-sprint review.  
**Weak spot:** Hours matrix needs a strong Hours tab.

### B — Hours explorer

- Stories / Tasks toggle
- Person × weekday matrix
- Cell click opens side panel with ticket keys + hours (instead of cramming keys into every cell)

**Strength:** Fixes the worst readability problem.  
**Weak spot:** Needs a thin KPI header so completion/velocity aren’t buried.

### C — Attention triage

Surface first:

1. Unfinished tickets
2. Done-with-remaining hygiene flags
3. Mid-sprint adds (churn)
4. Sub-task worklogs / remaining

**Strength:** Great for mid-sprint / SM review.  
**Weak spot:** Weak alone for hour audits.

### D — Hybrid (**recommended**)

Native shell with five tabs; exports stay shareable artifacts.

| Tab | Shows | Replaces in MD/HTML |
|-----|--------|---------------------|
| Overview | KPI chips, team metrics, goal | Header + KPI + Completion |
| Hours | Stories/Tasks matrix, cell detail drawer | Logged Hours tables |
| Alerts | Churn, sub-task remaining, sub-task worklogs, warn rows | Validation + churn + warn tickets |
| Tickets | Sortable/filterable status & remaining | Sprint Tickets table |

**No Chart tab / no bar graphs** in the redesigned Generate UI (optional: keep PNG export for sharing only, not as an in-app graph).

Actions on the page: **Open HTML** · **Reveal folder**.

**Why this wins:** Same data pipeline; only the Generate UI changes. Native Qt tables fix hours/tickets without throwing away the report format.

### App shell (related)

- Top **capsule** nav for workflow: Settings · Sprint · Configure · Generate
- **Help stays a separate tab** (not folded into the workflow) until users know the app
- Same capsule language for report section tabs on Generate

---

## Sample KPI snapshot (Wi-Fi_LMAC_2026_11)

| Metric | Value |
|--------|------:|
| Ticket completion | 83% |
| SP completion | 87% |
| Velocity | 0.70 SP/day |
| Story hours | 388h |
| Task hours | 10h |
| Unfinished | 3 |
| Hygiene ⚠ | 2 |
| Mid-sprint add | 1 |
| Sub-task worklogs | 2 |

---

## Suggested implementation order

1. **Slice 1:** Overview KPI strip + Alerts list + Tickets `QTableView` (no charts)
2. **Slice 2:** Hours tab (Stories/Tasks matrix + cell detail drawer)
3. **Slice 3:** Capsule app shell + polish; keep MD/HTML writers unchanged

**Implementation note:** Expose structured dicts from `report_generator` (already computed) to the GUI instead of round-tripping through HTML.

---

## Important: how “closed” vs “open” works today

The tool uses the ticket’s **current** Jira status at the moment you run the report — **not** the status as of sprint end.

“Done” = `status_category` is Done/Complete, **or** `status` is Resolved (`report_generator.py`).

See `docs/design/ticket-status-across-sprints.md` for move / re-run scenarios.

---

## How to reopen the interactive canvas later

If the live canvas won’t open in Cursor:

```bash
mkdir -p ~/.cursor/projects/home-kibikkan-sprint-tools/canvases
cp docs/design/report-page-redesign.canvas.tsx \
  ~/.cursor/projects/home-kibikkan-sprint-tools/canvases/report-page-redesign.canvas.tsx
```

Then open the canvas from Cursor’s canvases UI, or ask the agent to “open the report-page-redesign canvas.”

You can always implement from **this markdown brief** alone — the `.canvas.tsx` is only for the interactive mockups.

# Sprint Report Tools

Generate sprint reports (markdown) and burndown charts (PNG) from Jira data.

---

## Prerequisites

### 1. Python 3.10+

```bash
python3 --version   # must be 3.10 or later
```

### 2. Python Dependencies

```bash
cd sprint_tools
pip install -r requirements.txt
```

This installs:
- `matplotlib` — burndown chart generation
- `requests` — MCP gateway communication

### 3. Jira Authentication

The tools support two modes for fetching Jira data, auto-detected at runtime:

**Mode 1: MCP Gateway** (default when Cursor is available)
- Uses credentials from `~/.cursor/mcp.json` (the same PAT configured for the Jira MCP server in Cursor)
- Zero extra setup if you already have Jira MCP working in Cursor

**Mode 2: Direct Jira REST API** (for terminal use without Cursor)
- Falls back automatically if MCP gateway is unavailable or fails
- Can be forced with `--no-mcp`
- Uses your Jira Personal Access Token (PAT)

**PAT resolution priority** (first match wins):
1. `--jira-token` CLI argument
2. `JIRA_TOKEN` environment variable
3. `.env` file in sprint_tools directory
4. PAT extracted from `~/.cursor/mcp.json` (if available)
5. Interactive prompt (asks you to enter the PAT)

**Setting up the PAT:**

```bash
# Option A: .env file (recommended for terminal use)
cp .env.defaults .env
# Edit .env and set your token:
#   JIRA_TOKEN=your-personal-access-token

# Option B: Environment variable
export JIRA_TOKEN=your-personal-access-token

# Option C: Let the script prompt you interactively
python3 fetch_via_mcp.py --no-mcp --config sprint_report_config.md
# → will ask for PAT if not found elsewhere
```

**Creating a Jira PAT:**
1. Go to Jira → Profile (top-right avatar) → Personal Access Tokens
2. Create a new token with read access
3. Copy the token value

**Jira URL configuration:**

The default Jira URL is `https://jira.silabs.com`. To override:
- `--jira-url https://your-jira.example.com` on the command line
- Set `JIRA_BASE_URL=https://your-jira.example.com` in `.env`
- Or edit `.env.defaults` to change the default for your team

**Verify MCP setup** (only needed for Mode 1):
```bash
cat ~/.cursor/mcp.json | python3 -c "
import sys, json
d = json.load(sys.stdin)
for k, v in d.get('mcpServers', {}).items():
    if 'jira' in k.lower():
        print(f'  Found: {k} ({v.get(\"type\",\"?\")})')
"
```

---

## Quick Start

```bash
cd sprint_tools

# Full run: fetch Jira data + generate report + burndown chart
./run.sh

# Or with a known board ID (faster, skips board search)
./run.sh --board-id 1325
```

Output files appear in `./output/`:
- `sprint_report_<name>.md` — full text report
- `sprint_burndown_<name>.png` — burndown chart

---

## Configuration — `sprint_report_config.md`

Edit this file before each sprint. Below is a field-by-field guide.

### Sprint Details

| Field | Format | Example | Notes |
|-------|--------|---------|-------|
| **Sprint Name** | Backtick-wrapped string | `` `Wi-Fi_LMAC_2026_5` `` | Must match the Jira sprint name **exactly** (case-sensitive). The script uses this to find the sprint. |
| **Sprint Duration (weeks)** | Number | `` `2` `` | Used for capacity calculation (working days = weeks × 5). |

### Team Members

A table of all sprint participants. Each row has:

| Column | Values | Effect |
|--------|--------|--------|
| Name | Full display name | Must match the **Jira display name** exactly (used to match worklogs). |
| Role | Any text | For reference only, not used in calculations. |
| Include in Report | `Yes` / `No` | `No` excludes the person from all calculations (e.g., managers). |

**Example:**
```markdown
| # | Name | Role | Include in Report |
|---|------|------|-------------------|
| 1 | Sunil Jangiti | Developer | Yes |
| 2 | Trinadh Angara | Manager | No |
```

**When to update:** Add new members, remove people who left, set `No` for anyone not doing sprint work.

### Capacity Adjustments

#### Meeting Days Reserved

```markdown
- **Days reserved**: `1`
```

This many days are deducted from **each person's** capacity. For a 2-week sprint (10 working days) with 1d reserved → 9 effective days (72h) per person.

#### Planned Leaves

```markdown
| Name | Leave Days | Notes |
|------|-----------|-------|
| Kiran Bikkanoori | 3 | 3d leave |
| | | |
```

Add a row for each person with planned leave. Name must match the Team Members table exactly. Leave blank rows for unused slots.

#### Other Non-Development Activities

```markdown
| Name | Hours Excluded | Reason |
|------|---------------|--------|
| Jane Doe | 8 | Production support rotation |
```

Hours deducted from a person's capacity for recurring non-sprint work (support, mentoring, etc.).

### Extra Tickets

Tickets **not** in the sprint that should still be tracked:

```markdown
| Ticket Key | Assignee | Notes |
|------------|----------|-------|
| PROJ-999 | Jane Doe | Backlog item being worked on |
```

### Tickets to Exclude

Tickets **in** the sprint that should be ignored (umbrella/tracking tickets, duplicates):

```markdown
| Ticket Key | Reason |
|------------|--------|
| PROJ-100 | Umbrella story, no actual work |
```

### Report Options

| Option | Values | Default | Effect |
|--------|--------|---------|--------|
| **Report Date** | `YYYY-MM-DD` or empty | Today | Worklogs and burndown chart cut off at this date. Use for mid-sprint snapshots. |
| **Exclude parent story estimates** | `Yes` / `No` | `Yes` | Prevents double-counting when parent stories have estimates that duplicate sub-task totals. |
| **Show per-ticket worklog details** | `Yes` / `No` | `Yes` | Includes the per-ticket breakdown table for each person. |
| **Show daily log gaps** | `Yes` / `No` | `Yes` | Shows days where a team member logged zero hours. |

### Sprint Metrics Definitions

This section is informational — it documents what completion rate and velocity mean. No changes needed unless you want to update the target thresholds (targets are displayed in the report but not enforced by code).

### What to Change Each Sprint

Typically you only need to update these fields:

1. **Sprint Name** — new sprint name
2. **Planned Leaves** — clear old entries, add new ones
3. **Tickets to Exclude** — clear old entries, add new ones if needed
4. **Team Members** — add/remove members or change Include status
5. **Report Date** — clear it (leave empty for today) unless you want a specific date

---

## Usage

### Full Run (recommended)

```bash
./run.sh
```

This runs two steps:
1. **Fetch data from Jira** — connects via MCP gateway (or falls back to direct REST API)
2. **Generate report + chart** — produces the markdown report and burndown PNG

### Common Options

```bash
# Force direct REST API (no Cursor/MCP needed)
./run.sh --no-mcp

# Override Jira URL
./run.sh --no-mcp --jira-url https://your-jira.example.com

# Only fetch data, don't generate report yet
./run.sh --fetch-only

# Re-generate report from existing data (no Jira fetch)
./run.sh --report-only

# Custom config file
./run.sh -c /path/to/my_config.md

# Custom output directory
./run.sh -o ./my_output

# Generate REPORT_FORMAT.md (field reference doc)
./run.sh --generate-format

# Clean up all generated files
./run.sh --cleanup
```

### Running Python Scripts Directly

If you prefer to run the scripts individually:

```bash
# Step 1: Fetch Jira data (auto-detects MCP or REST)
python3 fetch_via_mcp.py --config sprint_report_config.md --board-id 1325

# Step 1 (alt): Force direct REST API
python3 fetch_via_mcp.py --config sprint_report_config.md --no-mcp --board-id 1325

# Step 2: Generate report + chart
python3 sprint_report.py \
  --config sprint_report_config.md \
  --data sprint_data_Wi-Fi_LMAC_2026_5.json \
  --output-dir ./output

# Report only (no chart, no matplotlib needed)
python3 sprint_report.py -c sprint_report_config.md -d sprint_data_*.json --report-only

# Chart only
python3 sprint_report.py -c sprint_report_config.md -d sprint_data_*.json --chart-only

# Generate report format reference
python3 sprint_report.py --generate-format -o ./output
```

### Using the AI Assistant

You can also use the Cursor AI assistant to run the tools:

- **Full sprint report**: "Generate a sprint report using `sprint_report_config.md`"
- **Mid-sprint check**: "Generate a sprint report as of Mar 10 using the config"
- **Check today's logs**: "Using `sprint_report_config.md`, who hasn't logged work today?"
- **Specific person**: "Show me Kiran's planned vs logged from the config"
---

## File Structure

```
sprint_tools/
├── run.sh                   # Main entry point (orchestrates everything)
├── sprint_report_config.md  # Configuration (edit per sprint)
├── fetch_via_mcp.py         # Fetches Jira data (MCP gateway or direct REST) → JSON
├── sprint_report.py         # Generates report + chart from JSON
├── config_parser.py         # Parses sprint_report_config.md
├── report_generator.py      # Produces the markdown text report
├── report_format.py         # REPORT_FORMAT.md content (field reference)
├── burndown_chart.py        # Produces the burndown PNG
├── utils.py                 # Shared helpers (Jira time parsing, etc.)
├── export_sprint_data.py    # Schema docs + manual data conversion helpers
├── .env.defaults            # Default config (JIRA_BASE_URL); copy to .env to override
├── requirements.txt         # Python dependencies
└── README.md                # This file
```

---

## Data Flow

```
Jira (MCP or REST) ──→ fetch_via_mcp.py ──→ sprint_data_*.json ─┐
                                                                  │
sprint_report_config.md ──────────────────────────────────────────┤
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

## Report Sections

The generated report includes these sections (see `REPORT_FORMAT.md` for detailed field descriptions):

1. **Team Capacity** — effective days/hours per person
2. **Planned vs Logged Work** — estimates minus pre-sprint work vs actual logged hours
3. **Per-Ticket Worklog Details** — breakdown per ticket per person
4. **Ticket Status Distribution** — counts by status
5. **Daily Log Gaps** — days with no logged work
6. **Sprint Completion & Velocity** — completion rate, story-point velocity, per-person breakdown
7. **Carried-Over Closed Tickets** — tickets closed before sprint (excluded from all metrics)
8. **Sprint Health Summary** — consolidated metrics
9. **Burndown Chart** — remaining work vs ideal, daily logged hours

To generate the full field reference:
```bash
./run.sh --generate-format
# or
python3 sprint_report.py --generate-format -o ./output
```

---

## Sprint Workflow Checklist

Before each sprint:
1. Update `sprint_report_config.md`:
   - Sprint name (must match Jira exactly)
   - Team members (add/remove, set included/excluded)
   - Planned leaves
   - Any excluded tickets
2. Run `pip install -r requirements.txt` (first time or after updates)
3. Verify Jira access: either MCP gateway (`~/.cursor/mcp.json`) or `JIRA_TOKEN` in `.env`

Generate the report:
```bash
./run.sh --board-id 1325
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `MCP gateway failed: ...` | MCP is down or misconfigured; script auto-falls back to direct REST API |
| `No Jira PAT found` | Set `JIRA_TOKEN` in `.env`, env var, or pass `--jira-token`. Or configure MCP in Cursor |
| `Error: sprint not found` | Check sprint name in config matches Jira exactly (case-sensitive) |
| `ModuleNotFoundError: matplotlib` | Run `pip install -r requirements.txt` |
| `Story points showing as N/A` | Your Jira uses `customfield_10344` — this is already configured |
| Burndown chart looks empty | Check that team members have logged worklogs in Jira for the sprint dates |
| Pre-sprint tickets inflating metrics | They are auto-detected and excluded; check the "Carried-Over" section |

---

## Data JSON Schema

The intermediate JSON file (`sprint_data_*.json`) has this structure:

```json
{
  "sprint": {
    "name": "Sprint_Name",
    "start_date": "2026-03-04",
    "end_date": "2026-03-17",
    "goal": "Optional sprint goal"
  },
  "issues": [
    {
      "key": "PROJ-123",
      "summary": "Ticket title",
      "status": "In Progress",
      "status_category": "In Progress",
      "issuetype_name": "Sub-task",
      "issuetype_subtask": true,
      "has_subtasks": false,
      "type": "Sub-task",
      "assignee": "Jane Doe",
      "estimate_hours": 16.0,
      "estimate_raw": "2d",
      "story_points": 3.0,
      "resolution_date": "",
      "parent_key": "PROJ-100"
    }
  ],
  "worklogs": {
    "PROJ-123": [
      {
        "started": "2026-03-05",
        "seconds": 28800,
        "author": "Jane Doe"
      }
    ]
  }
}
```

`type` is **`Story`**, **`Task`**, or **`Sub-task`**, derived from Jira **issue type** and **parent** link (see `utils.classify_issue_bucket`). Older JSON may still say `Parent` / `Standalone`; the report normalizes those to Story / Task.

To generate a blank template:
```bash
python3 export_sprint_data.py --template -o sprint_data.json
```

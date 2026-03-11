# Sprint Report Tools

Generate sprint reports (markdown), burndown charts (PNG), and PR cycle time
analysis from Jira and GitHub data.

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

### 3. Jira MCP Server (for data fetching)

The tools fetch Jira data through the **MCP gateway** (same credentials Cursor IDE uses).
The MCP config is auto-detected from `~/.cursor/mcp.json`.

**Verify it exists:**
```bash
cat ~/.cursor/mcp.json | python3 -c "
import sys, json
d = json.load(sys.stdin)
for k, v in d.get('mcpServers', {}).items():
    if 'jira' in k.lower():
        print(f'  Found: {k} ({v.get(\"type\",\"?\")})')
"
```

If no Jira MCP server is found, set it up in Cursor:
1. Open Cursor Settings → MCP Servers
2. Add your Jira MCP server (HTTP type)
3. Verify it appears in `~/.cursor/mcp.json`

### 4. GitHub CLI (optional — for PR cycle time report)

The PR cycle time section is **fully optional**. If `gh` is not installed or not
authenticated, all other report sections (capacity, velocity, burndown, etc.) still
work normally. The report will include a note that cycle time data is unavailable.

To enable cycle time analysis:

```bash
# Install (Linux/Debian/Ubuntu)
sudo apt install gh
# Or download from https://cli.github.com/

# Authenticate
gh auth login
# Choose: GitHub.com → HTTPS → Login with a web browser

# Verify
gh auth status
```

To explicitly suppress the "unavailable" note in the report:
```bash
./run.sh --skip-cycle-time
```

---

## Quick Start

```bash
cd sprint_tools

# Full run: fetch Jira data + generate report + burndown chart + cycle time
./run.sh

# Or with a known board ID (faster, skips board search)
./run.sh --board-id 1325
```

Output files appear in `./output/`:
- `sprint_report_<name>.md` — full text report
- `sprint_burndown_<name>.png` — burndown chart
- `cycle_time_data_<name>.json` — raw PR metrics (if cycle time enabled)

---

## Configuration — `sprint_report_config.md`

Edit this file before each sprint. Below is a field-by-field guide.

### Sprint Details

| Field | Format | Example | Notes |
|-------|--------|---------|-------|
| **Sprint Name** | Backtick-wrapped string | `` `Wi-Fi_LMAC_2026_5` `` | Must match the Jira sprint name **exactly** (case-sensitive). The script uses this to find the sprint. |
| **Sprint Duration (weeks)** | Number | `` `2` `` | Used for capacity calculation (working days = weeks × 5). |
| **GitHub Repo** | `Owner/RepoName` | `` `SiliconLabsInternal/wifi-nwp-firmware` `` | Required for PR cycle time report. Leave empty to skip. |

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
| **Generate PR cycle time report** | `Yes` / `No` | `Yes` | Enables GitHub PR analysis. Requires `gh` CLI and GitHub Repo to be set. |

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

This runs three steps:
1. **Fetch data from Jira** — connects to MCP gateway, downloads sprint issues and worklogs
2. **PR cycle time analysis** — queries GitHub for PR metrics (if `gh` is set up)
3. **Generate report + chart** — produces the markdown report and burndown PNG

### Common Options

```bash
# Override GitHub repo from command line
./run.sh --gh-repo SiliconLabsInternal/wifi-nwp-firmware

# Skip cycle time report (no GitHub needed)
./run.sh --skip-cycle-time

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
# Step 1: Fetch Jira data
python3 fetch_via_mcp.py --config sprint_report_config.md --board-id 1325

# Step 2: Generate cycle time data (optional)
python3 cycle_time_report.py \
  --data sprint_data_Wi-Fi_LMAC_2026_5.json \
  --config sprint_report_config.md \
  --repo SiliconLabsInternal/wifi-nwp-firmware \
  --output-dir ./output

# Step 3: Generate report + chart
python3 sprint_report.py \
  --config sprint_report_config.md \
  --data sprint_data_Wi-Fi_LMAC_2026_5.json \
  --output-dir ./output \
  --cycle-time-data ./output/cycle_time_data_Wi-Fi_LMAC_2026_5.json \
  --gh-repo SiliconLabsInternal/wifi-nwp-firmware

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
- **Cycle time only**: "Generate the PR cycle time report for the current sprint"

---

## File Structure

```
sprint_tools/
├── run.sh                   # Main entry point (orchestrates everything)
├── sprint_report_config.md  # Configuration (edit per sprint)
├── fetch_via_mcp.py         # Fetches Jira data via MCP gateway → JSON
├── cycle_time_report.py     # Fetches GitHub PR metrics → JSON
├── sprint_report.py         # Generates report + chart from JSON
├── config_parser.py         # Parses sprint_report_config.md
├── report_generator.py      # Produces the markdown text report
├── report_format.py         # REPORT_FORMAT.md content (field reference)
├── burndown_chart.py        # Produces the burndown PNG
├── utils.py                 # Shared helpers (Jira time parsing, etc.)
├── export_sprint_data.py    # Schema docs + manual data conversion helpers
├── fetch_sprint_data.py     # Legacy: Jira REST API fetcher (PAT-based)
├── requirements.txt         # Python dependencies
└── README.md                # This file
```

---

## Data Flow

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
9. **PR Cycle Time** — coding/pickup/review/cycle time per PR (if enabled)
10. **Burndown Chart** — remaining work vs ideal, daily logged hours

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
3. Verify Jira MCP is connected (`~/.cursor/mcp.json` has a jira entry)
4. Verify GitHub CLI is authenticated (`gh auth status`)

Generate the report:
```bash
./run.sh --board-id 1325
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `Error: mcp.json not found` | Ensure `~/.cursor/mcp.json` exists with a Jira MCP server entry |
| `Error: no Jira HTTP MCP server found` | Add a Jira MCP server in Cursor Settings → MCP Servers |
| `Error: sprint not found` | Check sprint name in config matches Jira exactly (case-sensitive) |
| `Warning: 'gh' CLI not found` | Install GitHub CLI: `sudo apt install gh` or https://cli.github.com/ |
| `Warning: 'gh' CLI not authenticated` | Run `gh auth login` and follow the prompts |
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

To generate a blank template:
```bash
python3 export_sprint_data.py --template -o sprint_data.json
```

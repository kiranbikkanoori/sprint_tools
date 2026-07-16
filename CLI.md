# Sprint Report — CLI

Scriptable path for automation, headless runs, or Cursor MCP. For the desktop app, see [README.md](./README.md).

Generate sprint reports (markdown) and burndown charts (PNG) from Jira data via `run.sh` / Python scripts and `sprint_report_config.md`.

---

## Prerequisites

### Python 3.10+

```bash
python3 --version   # must be 3.10 or later
```

### Dependencies

```bash
cd sprint_tools
pip install -r requirements.txt
```

### Jira authentication

Two modes, auto-detected at runtime:

**Mode 1: MCP Gateway** (default when Cursor is available)

- Uses credentials from `~/.cursor/mcp.json`
- Zero extra setup if Jira MCP already works in Cursor

**Mode 2: Direct Jira REST API**

- Falls back if MCP is unavailable; force with `--no-mcp`
- Uses a Jira Personal Access Token (PAT)

**PAT resolution priority** (first match wins):

1. `--jira-token` CLI argument  
2. `JIRA_TOKEN` environment variable  
3. `.env` in the `sprint_tools` directory  
4. PAT from `~/.cursor/mcp.json`  
5. Interactive prompt  

```bash
# Option A: .env (recommended for terminal use)
cp .env.defaults .env
# Edit .env:
#   JIRA_TOKEN=your-personal-access-token
#   JIRA_BASE_URL=https://jira.silabs.com   # optional override

# Option B: environment variable
export JIRA_TOKEN=your-personal-access-token
```

Default Jira URL is `https://jira.silabs.com`. Override with `--jira-url` or `JIRA_BASE_URL` in `.env`.

---

## Quick start

```bash
cd sprint_tools

# Full run: fetch Jira data + generate report + burndown chart
./run.sh

# Known board ID (faster, skips board search)
./run.sh --board-id 1325
```

Output in `./output/`:

- `sprint_report_<name>.md`
- `sprint_burndown_<name>.png`

---

## Common options

```bash
# Force direct REST API (no Cursor/MCP)
./run.sh --no-mcp

# Override Jira URL
./run.sh --no-mcp --jira-url https://your-jira.example.com

# Only fetch data
./run.sh --fetch-only

# Re-generate from existing JSON (no Jira fetch)
./run.sh --report-only

# Custom config / output
./run.sh -c /path/to/my_config.md
./run.sh -o ./my_output

# Field reference doc
./run.sh --generate-format

# Clean generated files
./run.sh --cleanup
```

### Running scripts directly

```bash
python3 fetch_via_mcp.py --config sprint_report_config.md --board-id 1325

python3 fetch_via_mcp.py --config sprint_report_config.md --no-mcp --board-id 1325

python3 sprint_report.py \
  --config sprint_report_config.md \
  --data sprint_data_Wi-Fi_LMAC_2026_5.json \
  --output-dir ./output

python3 sprint_report.py -c sprint_report_config.md -d sprint_data_*.json --report-only
python3 sprint_report.py -c sprint_report_config.md -d sprint_data_*.json --chart-only
python3 sprint_report.py --generate-format -o ./output
```

---

## Configuration — `sprint_report_config.md`

Edit before each sprint.

### Sprint details

| Field | Example | Notes |
|-------|---------|-------|
| **Sprint Name** | `` `Wi-Fi_LMAC_2026_5` `` | Must match Jira **exactly** (case-sensitive) |
| **Sprint Duration (weeks)** | `` `2` `` | Working days = weeks × 5 |

### Team members

| Column | Effect |
|--------|--------|
| Name | Must match Jira **display name** (worklog matching) |
| Role | Reference only |
| Include in Report | `Yes` / `No` — `No` excludes from calculations |

### Capacity adjustments

- **Meeting days reserved** — deducted from each person's capacity  
- **Planned leaves** — name + leave days  
- **Other non-development activities** — name + hours excluded + reason  

### Extra / excluded tickets

- **Extra tickets** — not in the sprint, still tracked  
- **Tickets to exclude** — in the sprint, ignored (umbrellas, duplicates)  

### Report options

| Option | Default | Effect |
|--------|---------|--------|
| Report Date | Today | Cut-off for worklogs / burndown |
| Show per-ticket worklog details | Yes | Per-ticket breakdown per person |

### What to change each sprint

1. Sprint name  
2. Planned leaves  
3. Tickets to exclude  
4. Team members include flags  
5. Report date (clear for “today”)  

---

## Data flow

```
Jira (MCP or REST) ──→ fetch_via_mcp.py ──→ sprint_data_*.json ─┐
                                                                  │
sprint_report_config.md ──────────────────────────────────────────┤
                                                                  │
                                                                  ▼
                                                         sprint_report.py
                                                            │       │
                                                            ▼       ▼
                                                 sprint_report_*.md  sprint_burndown_*.png
```

---

## Report sections

1. Logged Hours by Person — Stories / Tasks  
2. Sprint KPI Summary  
3. Daily Log Gaps  
4. Sub-task Validation  
5. Sprint Completion & Velocity  
6. Sprint Tickets — Status & Remaining Work  
7. Burndown Chart  

```bash
./run.sh --generate-format
# or
python3 sprint_report.py --generate-format -o ./output
```

---

## Project layout (CLI-relevant)

```
sprint_tools/
├── run.sh                   # Main entry point
├── sprint_report_config.md  # Per-sprint config
├── fetch_via_mcp.py         # Jira fetch → JSON
├── sprint_report.py         # Report + chart
├── config_parser.py
├── report_generator.py
├── burndown_chart.py
├── utils.py
├── export_sprint_data.py
├── .env.defaults
└── requirements.txt
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `MCP gateway failed` | Script falls back to direct REST; or use `--no-mcp` |
| `No Jira PAT found` | Set `JIRA_TOKEN` in `.env`, env var, or `--jira-token` |
| `Error: sprint not found` | Sprint name in config must match Jira exactly |
| `ModuleNotFoundError: matplotlib` | `pip install -r requirements.txt` |
| Empty burndown | Team members need worklogs in the sprint date range |

---

## Data JSON schema

Intermediate file `sprint_data_*.json`:

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
      "assignee": "Jane Doe",
      "estimate_hours": 16.0,
      "story_points": 3.0,
      "type": "Sub-task"
    }
  ],
  "worklogs": {
    "PROJ-123": [
      { "started": "2026-03-05", "seconds": 28800, "author": "Jane Doe" }
    ]
  }
}
```

Blank template:

```bash
python3 export_sprint_data.py --template -o sprint_data.json
```

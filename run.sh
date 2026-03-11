#!/usr/bin/env bash
#
# Sprint Report Runner
# ====================
# Fetches data from Jira (via MCP gateway or direct REST API), generates the
# text report, burndown chart, and PR cycle time report.
#
# Usage:
#   ./run.sh                          # full run with defaults
#   ./run.sh -c /path/to/config.md    # custom config
#   ./run.sh --fetch-only             # only fetch data, skip report
#   ./run.sh --report-only            # only generate report from existing data
#   ./run.sh --board-id 1325          # optional: force a specific board
#   ./run.sh --gh-repo OWNER/REPO     # GitHub repo for PR cycle time report
#   ./run.sh --skip-cycle-time        # skip the PR cycle time report
#   ./run.sh --no-mcp                 # skip MCP, use direct Jira REST API
#   ./run.sh --jira-url URL           # override Jira base URL
#   ./run.sh --cleanup                # delete generated files (data, output, pycache)
#   ./run.sh --help
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Defaults ─────────────────────────────────────────────────────────────────
CONFIG="sprint_report_config.md"
OUTPUT_DIR="./output"
BOARD_ID=""
MCP_CONFIG=""
GH_REPO=""
CLEANUP=false
FETCH_ONLY=false
REPORT_ONLY=false
SKIP_CYCLE_TIME=false
GENERATE_FORMAT=false
NO_MCP=false
JIRA_URL=""
JIRA_TOKEN_ARG=""

# ── Parse args ───────────────────────────────────────────────────────────────
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  -c, --config PATH       Path to sprint_report_config.md (default: sprint_report_config.md)
  -o, --output-dir DIR    Output directory (default: ./output)
  --board-id ID           Jira board ID (skips board search; your board: 1325)
  --mcp-config PATH       Path to mcp.json (default: auto-detect ~/.cursor/mcp.json)
  --no-mcp                Skip MCP gateway, use direct Jira REST API
  --jira-url URL          Jira base URL (default: from .env.defaults or https://jira.silabs.com)
  --jira-token TOKEN      Jira PAT (prefer JIRA_TOKEN env var or .env file instead)
  --gh-repo OWNER/REPO    GitHub repo for cycle time report (reads from config if omitted)
  --skip-cycle-time       Skip the PR cycle time report (Step 3)
  --generate-format       Generate REPORT_FORMAT.md (field reference) and exit
  --cleanup               Remove sprint_data JSON after generating report
  --fetch-only            Only fetch data from Jira, skip report generation
  --report-only           Only generate report from existing data (skip fetch)
  -h, --help              Show this help

Examples:
  ./run.sh                                    # Full run (auto-detects MCP or REST)
  ./run.sh --board-id 1325                    # Full run, known board
  ./run.sh --no-mcp                           # Full run, direct REST API (no Cursor needed)
  ./run.sh --gh-repo Org/repo                 # Full run with cycle time for specific repo
  ./run.sh --report-only -o ./my_output       # Re-generate from existing data
  ./run.sh --skip-cycle-time                  # Run without PR cycle time analysis
  ./run.sh --generate-format                  # Generate field reference doc
  ./run.sh --cleanup                          # Delete generated files
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -c|--config)       CONFIG="$2"; shift 2 ;;
        -o|--output-dir)   OUTPUT_DIR="$2"; shift 2 ;;
        --board-id)        BOARD_ID="$2"; shift 2 ;;
        --mcp-config)      MCP_CONFIG="$2"; shift 2 ;;
        --gh-repo)         GH_REPO="$2"; shift 2 ;;
        --skip-cycle-time) SKIP_CYCLE_TIME=true; shift ;;
        --generate-format) GENERATE_FORMAT=true; shift ;;
        --no-mcp)          NO_MCP=true; shift ;;
        --jira-url)        JIRA_URL="$2"; shift 2 ;;
        --jira-token)      JIRA_TOKEN_ARG="$2"; shift 2 ;;
        --cleanup)         CLEANUP=true; shift ;;
        --fetch-only)      FETCH_ONLY=true; shift ;;
        --report-only)     REPORT_ONLY=true; shift ;;
        -h|--help)         usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

# ── Validate ─────────────────────────────────────────────────────────────────
if [[ ! -f "$CONFIG" ]]; then
    echo "Error: config not found: $CONFIG"
    exit 1
fi

# Extract sprint name from config for file naming
SPRINT_NAME=$(grep 'Sprint Name' "$CONFIG" | grep -oP '`[^`]+`' | tr -d '`' | head -1)
if [[ -z "$SPRINT_NAME" ]]; then
    echo "Error: could not extract sprint name from $CONFIG"
    exit 1
fi
SAFE_NAME="${SPRINT_NAME// /_}"
DATA_FILE="sprint_data_${SAFE_NAME}.json"

# Extract GitHub repo from config if not provided via --gh-repo
if [[ -z "$GH_REPO" ]]; then
    GH_REPO=$(grep 'GitHub Repo' "$CONFIG" | grep -oP '`[^`]+`' | tr -d '`' | head -1) || true
fi

# ── Cleanup-only mode ────────────────────────────────────────────────────────
if [[ "$CLEANUP" == true && "$FETCH_ONLY" == false && "$REPORT_ONLY" == false ]]; then
    echo "── Cleanup ──"
    rm -vf sprint_data_*.json 2>/dev/null || true
    rm -rf output 2>/dev/null && echo "  Removed output/" || true
    find "$SCRIPT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    echo "  Done."
    exit 0
fi

# ── Generate-format-only mode ─────────────────────────────────────────────
if [[ "$GENERATE_FORMAT" == true ]]; then
    echo "── Generating REPORT_FORMAT.md ──"
    mkdir -p "$OUTPUT_DIR"
    python3 sprint_report.py --generate-format -o "$OUTPUT_DIR"
    exit 0
fi

echo "=============================================="
echo "  Sprint Report: ${SPRINT_NAME}"
echo "=============================================="
echo "  Config:      $CONFIG"
echo "  Data file:   $DATA_FILE"
echo "  Output dir:  $OUTPUT_DIR"
echo "  GitHub repo: ${GH_REPO:-(not set, cycle time will be skipped)}"
echo ""

# ── Step 1: Fetch data ──────────────────────────────────────────────────────
if [[ "$REPORT_ONLY" == false ]]; then
    echo "── Step 1: Fetching data from Jira ──"

    FETCH_ARGS=(--config "$CONFIG" --output "$DATA_FILE")
    [[ -n "$BOARD_ID" ]] && FETCH_ARGS+=(--board-id "$BOARD_ID")
    [[ -n "$MCP_CONFIG" ]] && FETCH_ARGS+=(--mcp-config "$MCP_CONFIG")
    [[ "$NO_MCP" == true ]] && FETCH_ARGS+=(--no-mcp)
    [[ -n "$JIRA_URL" ]] && FETCH_ARGS+=(--jira-url "$JIRA_URL")
    [[ -n "$JIRA_TOKEN_ARG" ]] && FETCH_ARGS+=(--jira-token "$JIRA_TOKEN_ARG")

    python3 fetch_via_mcp.py "${FETCH_ARGS[@]}"
    echo ""
else
    if [[ ! -f "$DATA_FILE" ]]; then
        echo "Error: --report-only but data file not found: $DATA_FILE"
        echo "Run without --report-only first to fetch data."
        exit 1
    fi
    echo "── Step 1: Skipped (--report-only, using existing $DATA_FILE) ──"
    echo ""
fi

# ── Step 2: PR Cycle Time analysis ──────────────────────────────────────────
CYCLE_TIME_JSON=""
if [[ "$FETCH_ONLY" == false && "$SKIP_CYCLE_TIME" == false && -n "$GH_REPO" ]]; then
    echo "── Step 2: Generating PR cycle time data ──"

    CYCLE_TIME_JSON="$OUTPUT_DIR/cycle_time_data_${SAFE_NAME}.json"

    if ! command -v gh &>/dev/null; then
        echo "  Note: 'gh' CLI not installed — cycle time section will show as unavailable."
        echo "  To enable: install from https://cli.github.com/ and run 'gh auth login'"
        echo ""
    elif ! gh auth token &>/dev/null 2>&1; then
        echo "  Note: 'gh' CLI not authenticated — cycle time section will show as unavailable."
        echo "  To enable: run 'gh auth login'"
        echo ""
    else
        mkdir -p "$OUTPUT_DIR"
        python3 cycle_time_report.py \
            --data "$DATA_FILE" \
            --config "$CONFIG" \
            --repo "$GH_REPO" \
            --output-dir "$OUTPUT_DIR"
        echo ""
    fi
elif [[ "$FETCH_ONLY" == false && "$SKIP_CYCLE_TIME" == false && -z "$GH_REPO" ]]; then
    echo "── Step 2: Skipped (no GitHub repo configured) ──"
    echo "  Set 'GitHub Repo' in $CONFIG or use --gh-repo OWNER/REPO"
    echo ""
else
    echo "── Step 2: Skipped ──"
    echo ""
fi

# ── Step 3: Generate sprint report + chart ─────────────────────────────────
if [[ "$FETCH_ONLY" == false ]]; then
    echo "── Step 3: Generating sprint report and chart ──"
    mkdir -p "$OUTPUT_DIR"

    REPORT_ARGS=(--config "$CONFIG" --data "$DATA_FILE" --output-dir "$OUTPUT_DIR")
    if [[ -n "$CYCLE_TIME_JSON" ]]; then
        REPORT_ARGS+=(--cycle-time-data "$CYCLE_TIME_JSON")
        if [[ -f "$CYCLE_TIME_JSON" && -n "$GH_REPO" ]]; then
            REPORT_ARGS+=(--gh-repo "$GH_REPO")
        fi
    fi

    python3 sprint_report.py "${REPORT_ARGS[@]}"
    echo ""
else
    echo "── Step 3: Skipped (--fetch-only) ──"
    echo ""
fi

# ── Output summary ──────────────────────────────────────────────────────────
if [[ "$FETCH_ONLY" == false ]]; then
    echo "── Output files ──"
    ls -lh "$OUTPUT_DIR"/*"${SAFE_NAME}"* 2>/dev/null || echo "  (no output files found)"
    echo ""
fi

echo "=============================================="
echo "  Done!"
echo "=============================================="

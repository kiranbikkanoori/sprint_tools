#!/usr/bin/env bash
#
# Sprint Report Runner
# ====================
# Fetches data from Jira (via MCP gateway or direct REST API), generates the
# text report and burndown chart.
#
# Usage:
#   ./run.sh                          # full run with defaults
#   ./run.sh -c /path/to/config.md    # custom config
#   ./run.sh --fetch-only             # only fetch data, skip report
#   ./run.sh --report-only            # only generate report from existing data
#   ./run.sh --board-id 1325          # optional: force a specific board
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
CLEANUP=false
FETCH_ONLY=false
REPORT_ONLY=false
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
  --generate-format       Generate REPORT_FORMAT.md (field reference) and exit
  --cleanup               Remove sprint_data JSON after generating report
  --fetch-only            Only fetch data from Jira, skip report generation
  --report-only           Only generate report from existing data (skip fetch)
  -h, --help              Show this help

Examples:
  ./run.sh                                    # Full run (auto-detects MCP or REST)
  ./run.sh --board-id 1325                    # Full run, known board
  ./run.sh --no-mcp                           # Full run, direct REST API (no Cursor needed)
  ./run.sh --report-only -o ./my_output       # Re-generate from existing data
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

# ── Step 2: Generate sprint report + chart ─────────────────────────────────
if [[ "$FETCH_ONLY" == false ]]; then
    echo "── Step 2: Generating sprint report and chart ──"
    mkdir -p "$OUTPUT_DIR"

    python3 sprint_report.py --config "$CONFIG" --data "$DATA_FILE" --output-dir "$OUTPUT_DIR"
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

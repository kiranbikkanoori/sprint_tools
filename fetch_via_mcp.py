#!/usr/bin/env python3
"""
Fetch sprint data by calling Jira tools through the MCP gateway.

Reads the MCP server URL and auth token from ~/.cursor/mcp.json
(the same credentials Cursor IDE uses), so no extra Jira PAT is needed.

Usage
-----
    # Auto-detect mcp.json location
    python fetch_via_mcp.py --config ../sprint_report_config.md

    # Explicit mcp.json path
    python fetch_via_mcp.py --config ../sprint_report_config.md --mcp-config ~/.cursor/mcp.json

    # With known board ID (skips board search)
    python fetch_via_mcp.py --config ../sprint_report_config.md --board-id 1325
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_parser import parse_config
from utils import parse_jira_time_to_hours


# ── MCP HTTP Client ─────────────────────────────────────────────────────────

class McpClient:
    """Minimal MCP-over-HTTP client for calling tools on a Streamable HTTP server."""

    def __init__(self, url: str, headers: dict):
        self.url = url.rstrip("/")
        self.session = requests.Session()
        # Gateway requires both content types in Accept — set BEFORE auth headers
        self.session.headers["Content-Type"] = "application/json"
        self.session.headers["Accept"] = "application/json, text/event-stream"
        self.session.headers.update(headers)
        self.session_id = None
        self._initialize()

    def _initialize(self):
        """Send MCP initialize handshake and capture session ID."""
        resp = self._raw_post({
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "sprint-tools", "version": "1.0.0"},
            },
            "id": str(uuid.uuid4()),
        })
        if "Mcp-Session-Id" in resp.headers:
            self.session_id = resp.headers["Mcp-Session-Id"]
            self.session.headers["Mcp-Session-Id"] = self.session_id

        # Send initialized notification (expect 202)
        self.session.post(self.url, json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }, timeout=15)

    def _raw_post(self, body: dict) -> requests.Response:
        resp = self.session.post(self.url, json=body, timeout=60)
        resp.raise_for_status()
        return resp

    def call_tool(self, tool_name: str, arguments: dict) -> any:
        """Call an MCP tool and return the parsed result."""
        body = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": str(uuid.uuid4()),
        }
        resp = self._raw_post(body)
        content_type = resp.headers.get("Content-Type", "")

        if "text/event-stream" in content_type:
            return self._parse_sse(resp.text)
        else:
            data = resp.json()
            return self._extract_result(data)

    def _parse_sse(self, text: str) -> any:
        """Parse Server-Sent Events response to extract tool result."""
        for line in text.splitlines():
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    result = self._extract_result(data)
                    if result is not None:
                        return result
                except json.JSONDecodeError:
                    continue
        return None

    def _extract_result(self, data: dict) -> any:
        """Extract the text content from an MCP tool response."""
        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        result = data.get("result", {})
        content = result.get("content", [])
        for item in content:
            if item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except (json.JSONDecodeError, TypeError):
                    return item.get("text")
        return result


# ── Data conversion ─────────────────────────────────────────────────────────

def classify_issue(issue: dict) -> str:
    has_parent = issue.get("parent") is not None
    subtasks = issue.get("subtasks", [])
    has_subtasks = bool(subtasks) and len(subtasks) > 0
    if has_subtasks and not has_parent:
        return "Parent"
    if has_parent:
        return "Sub-task"
    return "Standalone"


STORY_POINT_FIELDS = [
    "story_points", "customfield_10344", "customfield_10028",
    "customfield_10016", "customfield_10026", "customfield_10004",
]


def extract_story_points(raw: dict) -> float | None:
    """Try common Jira story point field names, return first non-null value.

    Handles both plain numbers and {'value': X} dicts returned by some MCP servers.
    """
    for field_name in STORY_POINT_FIELDS:
        val = raw.get(field_name)
        if val is None:
            continue
        if isinstance(val, dict):
            val = val.get("value")
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return None


def convert_issue(raw: dict) -> dict:
    tt = raw.get("timetracking", {}) or {}
    est_raw = tt.get("original_estimate", "0") or "0"
    assignee = raw.get("assignee") or {}
    status = raw.get("status", {})

    resolution_date = raw.get("resolutiondate") or raw.get("resolution_date") or ""
    if isinstance(resolution_date, str):
        resolution_date = resolution_date[:10]

    return {
        "key": raw["key"],
        "summary": raw.get("summary", ""),
        "status": status.get("name", "Unknown"),
        "status_category": status.get("category", "Unknown"),
        "type": classify_issue(raw),
        "assignee": assignee.get("display_name", "Unassigned"),
        "estimate_hours": parse_jira_time_to_hours(est_raw),
        "estimate_raw": est_raw,
        "story_points": extract_story_points(raw),
        "resolution_date": resolution_date,
        "parent_key": (raw.get("parent") or {}).get("key"),
    }


def convert_worklog_entry(wl: dict) -> dict:
    started = wl.get("started", "")[:10]
    return {
        "started": started,
        "seconds": wl.get("timeSpentSeconds", 0),
        "author": wl.get("author", "Unknown"),
    }


# ── MCP config loading ─────────────────────────────────────────────────────

def find_mcp_config() -> Path | None:
    """Search standard locations for mcp.json."""
    candidates = [
        Path.home() / ".cursor" / "mcp.json",
        Path.cwd().parent / ".cursor" / "mcp.json",
        Path.cwd() / ".cursor" / "mcp.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_jira_mcp_config(mcp_path: Path) -> tuple[str, dict]:
    """Extract Jira MCP server URL and headers from mcp.json."""
    data = json.loads(mcp_path.read_text())
    servers = data.get("mcpServers", {})

    for name, cfg in servers.items():
        if "jira" in name.lower() and cfg.get("type") == "http":
            url = cfg["url"]
            headers = cfg.get("headers", {})
            return url, headers

    print("Error: no Jira HTTP MCP server found in mcp.json.", file=sys.stderr)
    print(f"Servers found: {list(servers.keys())}", file=sys.stderr)
    sys.exit(1)


# ── Sprint search (via MCP tools) ───────────────────────────────────────────

def find_sprint_by_name(client: McpClient, sprint_name: str) -> dict | None:
    """
    Find a sprint by name using JQL search.  This avoids having to know
    the board ID — Jira finds the sprint across all boards.
    """
    jql = f'sprint = "{sprint_name}"'
    result = client.call_tool("jira_search", {
        "jql": jql, "fields": "summary", "limit": 1,
    })
    issues = result.get("issues", [])
    if not issues:
        return None

    # We found issues in this sprint — now get the sprint details
    # by checking any issue's sprint field
    sample_key = issues[0]["key"]
    issue = client.call_tool("jira_get_issue", {
        "issue_key": sample_key, "fields": "*all",
    })
    fields = issue.get("fields", {})

    # Sprint info is in the 'sprint' field (Jira Agile)
    sprint_field = fields.get("sprint")
    if sprint_field and sprint_field.get("name") == sprint_name:
        return sprint_field

    # Fallback: check customfield_10020 (common sprint custom field)
    for cf_name in ["customfield_10020", "customfield_10100", "customfield_10010"]:
        cf = fields.get(cf_name)
        if isinstance(cf, list):
            for s in cf:
                if isinstance(s, dict) and s.get("name") == sprint_name:
                    return s
        elif isinstance(cf, dict) and cf.get("name") == sprint_name:
            return cf

    return None


def find_sprint_on_board(client: McpClient, board_id: str, sprint_name: str) -> dict | None:
    """Search for a sprint on a specific board (active → future → closed)."""
    all_found = []
    for state in ["active", "future", "closed"]:
        sprints = client.call_tool("jira_get_sprints_from_board", {
            "board_id": str(board_id), "state": state, "limit": 50,
        })
        if not sprints:
            continue
        for s in sprints:
            all_found.append(s)
            if s.get("name") == sprint_name:
                return s

    print(f"\n  Sprint '{sprint_name}' not found on board {board_id}.", file=sys.stderr)
    print(f"  Available sprints:", file=sys.stderr)
    for s in all_found[:15]:
        print(f"    - {s.get('name')} [{s.get('state')}]", file=sys.stderr)
    if len(all_found) > 15:
        print(f"    ... and {len(all_found) - 15} more", file=sys.stderr)
    return None


def find_board_via_mcp(client: McpClient, sprint_name: str) -> dict | None:
    """Find a board by deriving keywords from the sprint name."""
    keywords = sprint_name.replace("_", " ").split()
    while keywords and keywords[-1].isdigit():
        keywords.pop()
    if not keywords:
        keywords = sprint_name.replace("_", " ").split()

    for i in range(len(keywords), 0, -1):
        term = " ".join(keywords[:i])
        boards = client.call_tool("jira_get_agile_boards", {
            "board_name": term, "board_type": "scrum", "limit": 20,
        })
        if not boards:
            continue

        candidates = [b for b in boards if "copy" not in b.get("name", "").lower()]
        if not candidates:
            continue

        candidates.sort(key=lambda b: (
            not b.get("name", "").lower().startswith(term.lower()),
            len(b.get("name", "")),
        ))
        best = candidates[0]
        print(f"  Board matched '{term}' → {best['name']} (ID: {best['id']})")
        return best

    return None


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fetch sprint data via MCP gateway (uses credentials from mcp.json).",
    )
    parser.add_argument("--config", "-c", required=True, help="Path to sprint_report_config.md")
    parser.add_argument("--output", "-o", default=None, help="Output JSON path")
    parser.add_argument("--board-id", type=int, default=None, help="Jira board ID (skips search)")
    parser.add_argument("--mcp-config", default=None, help="Path to mcp.json (auto-detected if omitted)")
    args = parser.parse_args()

    # Load MCP config
    if args.mcp_config:
        mcp_path = Path(args.mcp_config)
    else:
        mcp_path = find_mcp_config()
    if not mcp_path or not mcp_path.exists():
        print("Error: mcp.json not found.", file=sys.stderr)
        print("Provide path with --mcp-config or ensure ~/.cursor/mcp.json exists.", file=sys.stderr)
        sys.exit(1)

    print(f"Using MCP config: {mcp_path}")
    url, headers = load_jira_mcp_config(mcp_path)
    print(f"Jira MCP gateway: {url}")

    config = parse_config(args.config)
    sprint_name = config.sprint_name
    if not sprint_name:
        print("Error: no sprint name in config.", file=sys.stderr)
        sys.exit(1)

    safe_name = sprint_name.replace(" ", "_")
    output_path = Path(args.output) if args.output else Path(f"sprint_data_{safe_name}.json")

    # Connect
    print("Connecting to MCP gateway...")
    client = McpClient(url, headers)
    print("Connected.")

    # ── Find sprint ──────────────────────────────────────────────────────
    sprint = None

    if args.board_id:
        # Board ID given explicitly — search on that board
        print(f"Looking for sprint '{sprint_name}' on board {args.board_id}")
        sprint = find_sprint_on_board(client, str(args.board_id), sprint_name)
    else:
        # Strategy 1: find sprint directly by name via JQL (fastest, no board needed)
        print(f"Searching for sprint: {sprint_name}")
        sprint = find_sprint_by_name(client, sprint_name)

        if not sprint:
            # Strategy 2: guess the board from sprint name, then search sprints
            print("  JQL lookup didn't return sprint details, trying board search...")
            board = find_board_via_mcp(client, sprint_name)
            if board:
                sprint = find_sprint_on_board(client, str(board["id"]), sprint_name)

    if not sprint:
        print(f"\nError: sprint '{sprint_name}' not found.", file=sys.stderr)
        print("Check that the sprint name in your config matches Jira exactly.", file=sys.stderr)
        sys.exit(1)

    sprint_id = str(sprint["id"])
    start_date = (sprint.get("start_date") or sprint.get("startDate", ""))[:10]
    end_date = (sprint.get("end_date") or sprint.get("endDate", ""))[:10]
    goal = sprint.get("goal", "")
    print(f"Found: {sprint_name} (ID: {sprint_id}, {start_date} → {end_date})")

    # ── Fetch issues (paginated) ─────────────────────────────────────────
    print("Fetching issues...", end="", flush=True)
    all_raw_issues = []
    start_at = 0
    while True:
        result = client.call_tool("jira_get_sprint_issues", {
            "sprint_id": sprint_id,
            "fields": "summary,status,issuetype,assignee,timetracking,parent,subtasks,resolutiondate,story_points,customfield_10344,customfield_10028,customfield_10016,customfield_10026,customfield_10004",
            "start_at": start_at,
            "limit": 50,
        })
        issues_batch = result.get("issues", [])
        all_raw_issues.extend(issues_batch)
        total = result.get("total", 0)
        print(f" {len(all_raw_issues)}/{total}", end="", flush=True)
        if start_at + len(issues_batch) >= total or not issues_batch:
            break
        start_at += len(issues_batch)
    print(" done.")

    issues = [convert_issue(i) for i in all_raw_issues]
    parent_keys = {i["key"] for i in issues if i["type"] == "Parent"}

    # ── Fetch worklogs ───────────────────────────────────────────────────
    tickets_to_fetch = [i["key"] for i in issues if i["key"] not in parent_keys]
    print(f"Fetching worklogs for {len(tickets_to_fetch)} tickets...", end="", flush=True)

    worklogs: dict[str, list[dict]] = {}
    for idx, key in enumerate(tickets_to_fetch):
        result = client.call_tool("jira_get_worklog", {"issue_key": key})
        raw_wl = result.get("worklogs", []) if isinstance(result, dict) else []
        worklogs[key] = [convert_worklog_entry(wl) for wl in raw_wl]
        if (idx + 1) % 5 == 0:
            print(f" {idx + 1}/{len(tickets_to_fetch)}", end="", flush=True)
    print(" done.")

    # ── Write JSON ───────────────────────────────────────────────────────
    data = {
        "sprint": {
            "name": sprint_name,
            "start_date": start_date,
            "end_date": end_date,
            "goal": goal,
        },
        "issues": issues,
        "worklogs": worklogs,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nSprint data exported to: {output_path}")
    print(f"Issues: {len(issues)} ({len(parent_keys)} parents, {len(tickets_to_fetch)} sub-tasks/standalone)")
    print(f"Worklogs: {sum(len(v) for v in worklogs.values())} entries")


if __name__ == "__main__":
    main()

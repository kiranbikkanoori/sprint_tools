#!/usr/bin/env python3
"""
Fetch sprint data from Jira and export to portable JSON.

Supports two modes (auto-detected):
  1. MCP gateway  — uses ~/.cursor/mcp.json (works inside Cursor)
  2. Direct REST   — uses Jira PAT from env var, .env file, mcp.json, or prompt

Usage
-----
    # Auto-detect mode (tries MCP first, falls back to direct REST)
    python fetch_via_mcp.py --config sprint_report_config.md

    # With known board ID (faster)
    python fetch_via_mcp.py --config sprint_report_config.md --board-id 1325

    # Force direct REST API (skip MCP)
    python fetch_via_mcp.py --config sprint_report_config.md --no-mcp

    # Provide PAT via env var
    JIRA_TOKEN=your-pat python fetch_via_mcp.py --config sprint_report_config.md

    # Override Jira URL
    python fetch_via_mcp.py --config sprint_report_config.md --jira-url https://jira.example.com
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path

import requests
from requests.auth import AuthBase

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_parser import parse_config
from mcp_client import McpClient, find_mcp_config, load_mcp_server_config
from utils import (
    classify_issue_bucket,
    extract_issuetype_info,
    extract_story_points,
    issue_has_subtasks,
    jira_issue_is_rest_api_shape,
    parse_jira_time_to_hours,
)


DEFAULT_JIRA_URL = "https://jira.silabs.com"
SPRINT_FIELDS_REST = (
    "summary,status,issuetype,assignee,timetracking,parent,subtasks,"
    "resolutiondate,customfield_10344,customfield_10028,customfield_10016,"
    "customfield_10026,customfield_10004"
)
SPRINT_FIELDS_MCP = (
    "summary,status,issuetype,assignee,timetracking,parent,subtasks,"
    "resolutiondate,story_points,customfield_10344,customfield_10028,"
    "customfield_10016,customfield_10026,customfield_10004"
)


# ── Direct Jira REST Client ─────────────────────────────────────────────────

class BearerAuth(AuthBase):
    def __init__(self, token: str):
        self.token = token

    def __call__(self, r):
        r.headers["Authorization"] = f"Bearer {self.token}"
        return r


class JiraRestClient:
    """Direct Jira REST API client using a PAT."""

    def __init__(self, base_url: str, pat: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = BearerAuth(pat)
        self.session.headers["Content-Type"] = "application/json"

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = self.session.get(f"{self.base_url}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def find_boards(self, name: str, board_type: str = "scrum") -> list[dict]:
        data = self._get("/rest/agile/1.0/board", {"type": board_type, "name": name, "maxResults": 20})
        return data.get("values", [])

    def get_sprints(self, board_id: int, state: str | None = None) -> list[dict]:
        """All sprints on the board (paginated). Required to find older *closed* sprints."""
        all_sprints: list[dict] = []
        start_at = 0
        page = 50
        while True:
            params: dict = {"startAt": start_at, "maxResults": page}
            if state:
                params["state"] = state
            data = self._get(f"/rest/agile/1.0/board/{board_id}/sprint", params)
            batch = data.get("values", [])
            all_sprints.extend(batch)
            if not batch:
                break
            total = data.get("total")
            if total is not None:
                if start_at + len(batch) >= int(total):
                    break
            elif data.get("isLast") is True or len(batch) < page:
                break
            start_at += len(batch)
        return all_sprints

    def get_sprint_issues(self, sprint_id: int, fields: str = SPRINT_FIELDS_REST) -> list[dict]:
        all_issues = []
        start_at = 0
        while True:
            params = {"fields": fields, "startAt": start_at, "maxResults": 50}
            data = self._get(f"/rest/agile/1.0/sprint/{sprint_id}/issue", params)
            issues = data.get("issues", [])
            all_issues.extend(issues)
            if start_at + len(issues) >= data.get("total", 0) or not issues:
                break
            start_at += len(issues)
        return all_issues

    def get_worklogs(self, issue_key: str) -> list[dict]:
        data = self._get(f"/rest/api/2/issue/{issue_key}/worklog")
        return data.get("worklogs", [])


# ── Shared data conversion ──────────────────────────────────────────────────

def convert_issue_mcp(raw: dict) -> dict:
    """Convert an issue from MCP gateway response (fields at top level)."""
    tt = raw.get("timetracking", {}) or {}
    est_raw = tt.get("original_estimate") or tt.get("originalEstimate", "0") or "0"
    rem_raw = tt.get("remaining_estimate") or tt.get("remainingEstimate", "0") or "0"
    assignee = raw.get("assignee") or {}
    status = raw.get("status", {})

    resolution_date = raw.get("resolutiondate") or raw.get("resolution_date") or ""
    if isinstance(resolution_date, str):
        resolution_date = resolution_date[:10]

    has_parent = raw.get("parent") is not None
    iname, is_sub = extract_issuetype_info(raw)
    has_subtasks = issue_has_subtasks(raw)
    return {
        "key": raw["key"],
        "summary": raw.get("summary", ""),
        "status": status.get("name", "Unknown"),
        "status_category": status.get("category", "Unknown"),
        "issuetype_name": iname or "Unknown",
        "issuetype_subtask": is_sub,
        "has_subtasks": has_subtasks,
        "type": classify_issue_bucket(
            issuetype_name=iname,
            has_parent=has_parent,
            issuetype_is_subtask=is_sub,
            has_subtasks=has_subtasks,
        ),
        "assignee": assignee.get("display_name", "Unassigned"),
        "estimate_hours": parse_jira_time_to_hours(est_raw),
        "estimate_raw": est_raw,
        "remaining_estimate_hours": parse_jira_time_to_hours(rem_raw),
        "remaining_estimate_raw": rem_raw,
        "story_points": extract_story_points(raw),
        "resolution_date": resolution_date,
        "parent_key": (raw.get("parent") or {}).get("key"),
    }


def convert_issue_rest(raw: dict) -> dict:
    """Convert an issue from direct Jira REST API response (fields nested)."""
    fields = raw.get("fields", {})
    tt = fields.get("timetracking", {}) or {}
    est_raw = tt.get("originalEstimate", "0") or "0"
    rem_raw = tt.get("remainingEstimate", "0") or "0"
    assignee = fields.get("assignee") or {}
    status = fields.get("status", {})
    parent = fields.get("parent")

    resolution_date = fields.get("resolutiondate") or ""
    if isinstance(resolution_date, str):
        resolution_date = resolution_date[:10]

    has_parent = parent is not None
    iname, is_sub = extract_issuetype_info(raw, rest_fields=fields)
    has_subtasks = issue_has_subtasks(raw, rest_fields=fields)
    return {
        "key": raw["key"],
        "summary": fields.get("summary", ""),
        "status": status.get("name", "Unknown"),
        "status_category": status.get("statusCategory", {}).get("name", "Unknown"),
        "issuetype_name": iname or "Unknown",
        "issuetype_subtask": is_sub,
        "has_subtasks": has_subtasks,
        "type": classify_issue_bucket(
            issuetype_name=iname,
            has_parent=has_parent,
            issuetype_is_subtask=is_sub,
            has_subtasks=has_subtasks,
        ),
        "assignee": assignee.get("displayName", "Unassigned"),
        "estimate_hours": parse_jira_time_to_hours(est_raw),
        "estimate_raw": est_raw,
        "remaining_estimate_hours": parse_jira_time_to_hours(rem_raw),
        "remaining_estimate_raw": rem_raw,
        "story_points": extract_story_points(fields),
        "resolution_date": resolution_date,
        "parent_key": parent.get("key") if parent else None,
    }


def convert_issue_auto(raw: dict) -> dict:
    """Use REST or flattened MCP mapping depending on how Jira/MCP returned the issue."""
    if jira_issue_is_rest_api_shape(raw):
        return convert_issue_rest(raw)
    return convert_issue_mcp(raw)


def convert_worklog_mcp(wl: dict) -> dict:
    """Convert worklog from MCP response."""
    return {
        "started": wl.get("started", "")[:10],
        "seconds": wl.get("timeSpentSeconds", 0),
        "author": wl.get("author", "Unknown"),
    }


def convert_worklog_rest(wl: dict) -> dict:
    """Convert worklog from direct REST response."""
    author_obj = wl.get("author", {})
    return {
        "started": wl.get("started", "")[:10],
        "seconds": wl.get("timeSpentSeconds", 0),
        "author": author_obj.get("displayName", "Unknown"),
    }


# ── MCP config loading ─────────────────────────────────────────────────────

def load_jira_mcp_config(mcp_path: Path) -> tuple[str, dict] | None:
    """Extract Jira MCP server URL and headers from mcp.json. Returns None if not found."""
    return load_mcp_server_config(mcp_path, "jira")


def extract_pat_from_mcp_config(mcp_path: Path) -> str | None:
    """Extract the Jira PAT from mcp.json Authorization header."""
    result = load_jira_mcp_config(mcp_path)
    if not result:
        return None
    _url, headers = result
    auth_header = headers.get("Authorization", "")
    for prefix in ["Token ", "Bearer ", "token ", "bearer "]:
        if auth_header.startswith(prefix):
            return auth_header[len(prefix):].strip()
    if auth_header:
        return auth_header.strip()
    return None


# ── Credential resolution ───────────────────────────────────────────────────

def load_env_file(path: Path):
    """Load KEY=VALUE pairs from a file into os.environ (setdefault, won't overwrite)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            value = value.strip().strip("'\"")
            os.environ.setdefault(key.strip(), value)


def resolve_jira_url(cli_arg: str | None) -> str:
    """Resolve Jira base URL with priority: CLI arg > env var > .env > .env.defaults > hardcoded."""
    if cli_arg:
        return cli_arg.rstrip("/")

    script_dir = Path(__file__).resolve().parent

    load_env_file(script_dir / ".env")
    load_env_file(script_dir.parent / ".env")
    load_env_file(script_dir / ".env.defaults")

    return os.environ.get("JIRA_BASE_URL", DEFAULT_JIRA_URL).rstrip("/")


def resolve_jira_pat(cli_arg: str | None) -> str:
    """Resolve Jira PAT with priority: CLI arg > env var > .env > mcp.json > interactive prompt."""
    if cli_arg:
        return cli_arg

    script_dir = Path(__file__).resolve().parent
    load_env_file(script_dir / ".env")
    load_env_file(script_dir.parent / ".env")

    token = os.environ.get("JIRA_TOKEN")
    if token:
        return token

    mcp_path = find_mcp_config()
    if mcp_path:
        pat = extract_pat_from_mcp_config(mcp_path)
        if pat:
            print(f"  Using Jira PAT extracted from {mcp_path}")
            return pat

    print()
    print("  No Jira PAT found in environment or mcp.json.")
    print("  Create one at: Jira → Profile → Personal Access Tokens")
    print("  Or set JIRA_TOKEN env var / add to .env file.")
    print()
    pat = getpass.getpass("  Enter Jira PAT: ").strip()
    if not pat:
        print("Error: no PAT provided.", file=sys.stderr)
        sys.exit(1)
    return pat


def resolve_jira_pat_optional(cli_arg: str | None) -> str | None:
    """
    Try to resolve a Jira PAT silently (no interactive prompt).
    Returns the PAT string or None if unavailable.
    """
    if cli_arg:
        return cli_arg

    script_dir = Path(__file__).resolve().parent
    load_env_file(script_dir / ".env")
    load_env_file(script_dir.parent / ".env")

    token = os.environ.get("JIRA_TOKEN")
    if token:
        return token

    mcp_path = find_mcp_config()
    if mcp_path:
        pat = extract_pat_from_mcp_config(mcp_path)
        if pat:
            return pat

    return None


# ── Sprint search (MCP) ────────────────────────────────────────────────────

def find_sprint_by_name_mcp(client: McpClient, sprint_name: str) -> dict | None:
    jql = f'sprint = "{sprint_name}"'
    result = client.call_tool("jira_search", {
        "jql": jql, "fields": "summary", "limit": 1,
    })
    issues = result.get("issues", [])
    if not issues:
        return None

    sample_key = issues[0]["key"]
    issue = client.call_tool("jira_get_issue", {
        "issue_key": sample_key, "fields": "*all",
    })
    fields = issue.get("fields", {})

    sprint_field = fields.get("sprint")
    if sprint_field and sprint_field.get("name") == sprint_name:
        return sprint_field

    for cf_name in ["customfield_10020", "customfield_10100", "customfield_10010"]:
        cf = fields.get(cf_name)
        if isinstance(cf, list):
            for s in cf:
                if isinstance(s, dict) and s.get("name") == sprint_name:
                    return s
        elif isinstance(cf, dict) and cf.get("name") == sprint_name:
            return cf
    return None


def _get_sprints_from_board_mcp(client: McpClient, board_id: str, state: str) -> list[dict]:
    """Paginate MCP sprint listing when the server supports ``startAt``; else first page only."""
    out: list[dict] = []
    start = 0
    limit = 50
    seen: set[str | int] = set()
    for _ in range(500):
        payload = {
            "board_id": str(board_id),
            "state": state,
            "limit": limit,
            "startAt": start,
        }
        sprints = client.call_tool("jira_get_sprints_from_board", payload)
        if isinstance(sprints, dict):
            sprints = sprints.get("sprints") or sprints.get("values") or []
        if not sprints:
            break
        new_count = 0
        for s in sprints:
            sid = s.get("id")
            if sid is not None and sid not in seen:
                seen.add(sid)
                out.append(s)
                new_count += 1
        if new_count == 0:
            break
        if len(sprints) < limit:
            break
        start += len(sprints)
    return out


def find_sprint_on_board_mcp(client: McpClient, board_id: str, sprint_name: str) -> dict | None:
    all_found = []
    for state in ["active", "future", "closed"]:
        sprints = _get_sprints_from_board_mcp(client, board_id, state)
        if not sprints:
            continue
        for s in sprints:
            all_found.append(s)
            if s.get("name") == sprint_name:
                return s

    _print_sprint_not_found(sprint_name, board_id, all_found)
    return None


def find_board_via_mcp(client: McpClient, sprint_name: str) -> dict | None:
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


# ── Sprint search (REST) ───────────────────────────────────────────────────

def find_sprint_on_board_rest(client: JiraRestClient, board_id: int, sprint_name: str) -> dict | None:
    all_found = []
    for state in ["active", "future", "closed"]:
        sprints = client.get_sprints(board_id, state=state)
        for s in sprints:
            all_found.append(s)
            if s.get("name") == sprint_name:
                return s

    _print_sprint_not_found(sprint_name, board_id, all_found)
    return None


def find_board_rest(client: JiraRestClient, sprint_name: str) -> dict | None:
    keywords = sprint_name.replace("_", " ").split()
    while keywords and keywords[-1].isdigit():
        keywords.pop()
    if not keywords:
        keywords = sprint_name.replace("_", " ").split()

    for i in range(len(keywords), 0, -1):
        term = " ".join(keywords[:i])
        boards = client.find_boards(term)
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


def _print_sprint_not_found(sprint_name: str, board_id, all_found: list):
    print(f"\n  Sprint '{sprint_name}' not found on board {board_id}.", file=sys.stderr)
    print("  Available sprints:", file=sys.stderr)
    for s in all_found[:15]:
        print(f"    - {s.get('name')} [{s.get('state')}]", file=sys.stderr)
    if len(all_found) > 15:
        print(f"    ... and {len(all_found) - 15} more", file=sys.stderr)


# ── Fetch via MCP ───────────────────────────────────────────────────────────

def fetch_via_mcp(
    mcp_url: str, mcp_headers: dict, sprint_name: str, board_id: int | None,
    output_path: Path, jira_url: str | None = None, jira_token: str | None = None,
):
    """Fetch sprint data using the MCP gateway."""
    print("Connecting to MCP gateway...")
    client = McpClient(mcp_url, mcp_headers)
    print("Connected.")

    sprint = None
    if board_id:
        print(f"Looking for sprint '{sprint_name}' on board {board_id}")
        sprint = find_sprint_on_board_mcp(client, str(board_id), sprint_name)
    else:
        print(f"Searching for sprint: {sprint_name}")
        sprint = find_sprint_by_name_mcp(client, sprint_name)
        if not sprint:
            print("  JQL lookup didn't return sprint details, trying board search...")
            board = find_board_via_mcp(client, sprint_name)
            if board:
                sprint = find_sprint_on_board_mcp(client, str(board["id"]), sprint_name)

    if not sprint:
        print(f"\nError: sprint '{sprint_name}' not found.", file=sys.stderr)
        sys.exit(1)

    sprint_id = str(sprint["id"])
    start_date = (sprint.get("start_date") or sprint.get("startDate", ""))[:10]
    end_date = (sprint.get("end_date") or sprint.get("endDate", ""))[:10]
    goal = sprint.get("goal", "")
    print(f"Found: {sprint_name} (ID: {sprint_id}, {start_date} → {end_date})")

    print("Fetching issues...", end="", flush=True)
    all_raw_issues = []
    start_at = 0
    while True:
        result = client.call_tool("jira_get_sprint_issues", {
            "sprint_id": sprint_id,
            "fields": SPRINT_FIELDS_MCP,
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

    issues = [convert_issue_auto(i) for i in all_raw_issues]

    tickets_to_fetch = [i["key"] for i in issues]
    print(f"Fetching worklogs for {len(tickets_to_fetch)} tickets...", end="", flush=True)
    worklogs: dict[str, list[dict]] = {}
    for idx, key in enumerate(tickets_to_fetch):
        result = client.call_tool("jira_get_worklog", {"issue_key": key})
        raw_wl = result.get("worklogs", []) if isinstance(result, dict) else []
        worklogs[key] = [convert_worklog_mcp(wl) for wl in raw_wl]
        if (idx + 1) % 5 == 0:
            print(f" {idx + 1}/{len(tickets_to_fetch)}", end="", flush=True)
    print(" done.")

    _write_output(sprint_name, start_date, end_date, goal, issues, worklogs, tickets_to_fetch, output_path)


# ── Fetch via direct REST ───────────────────────────────────────────────────

def fetch_via_rest(base_url: str, pat: str, sprint_name: str, board_id: int | None, output_path: Path):
    """Fetch sprint data using direct Jira REST API."""
    print(f"Connecting to Jira REST API at {base_url}...")
    client = JiraRestClient(base_url, pat)

    sprint = None
    if board_id:
        print(f"Looking for sprint '{sprint_name}' on board {board_id}")
        sprint = find_sprint_on_board_rest(client, board_id, sprint_name)
    else:
        print(f"Searching for sprint: {sprint_name}")
        board = find_board_rest(client, sprint_name)
        if board:
            sprint = find_sprint_on_board_rest(client, board["id"], sprint_name)

    if not sprint:
        print(f"\nError: sprint '{sprint_name}' not found.", file=sys.stderr)
        sys.exit(1)

    sprint_id = sprint["id"]
    start_date = (sprint.get("startDate") or sprint.get("start_date", ""))[:10]
    end_date = (sprint.get("endDate") or sprint.get("end_date", ""))[:10]
    goal = sprint.get("goal", "")
    print(f"Found: {sprint_name} (ID: {sprint_id}, {start_date} → {end_date})")

    print("Fetching issues...", end="", flush=True)
    all_raw_issues = client.get_sprint_issues(sprint_id, fields=SPRINT_FIELDS_REST)
    print(f" {len(all_raw_issues)} done.")

    issues = [convert_issue_rest(i) for i in all_raw_issues]

    tickets_to_fetch = [i["key"] for i in issues]
    print(f"Fetching worklogs for {len(tickets_to_fetch)} tickets...", end="", flush=True)
    worklogs: dict[str, list[dict]] = {}
    for idx, key in enumerate(tickets_to_fetch):
        raw_wl = client.get_worklogs(key)
        worklogs[key] = [convert_worklog_rest(wl) for wl in raw_wl]
        if (idx + 1) % 5 == 0:
            print(f" {idx + 1}/{len(tickets_to_fetch)}", end="", flush=True)
    print(" done.")

    _write_output(sprint_name, start_date, end_date, goal, issues, worklogs, tickets_to_fetch, output_path)


# ── Shared output ───────────────────────────────────────────────────────────

def _write_output(sprint_name, start_date, end_date, goal, issues, worklogs, tickets_to_fetch, output_path):
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

    story_n = sum(1 for i in issues if i["type"] == "Story")
    task_n = sum(1 for i in issues if i["type"] == "Task")
    sub_n = sum(1 for i in issues if i["type"] == "Sub-task")
    print(f"\nSprint data exported to: {output_path}")
    print(f"Issues: {len(issues)} ({story_n} stories, {task_n} tasks, {sub_n} sub-tasks)")
    print(f"Worklogs: {sum(len(v) for v in worklogs.values())} entries")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fetch sprint data from Jira (MCP gateway or direct REST API).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", "-c", required=True, help="Path to sprint_report_config.md")
    parser.add_argument("--output", "-o", default=None, help="Output JSON path")
    parser.add_argument("--board-id", type=int, default=None, help="Jira board ID (skips search)")
    parser.add_argument("--mcp-config", default=None, help="Path to mcp.json (auto-detected if omitted)")
    parser.add_argument("--no-mcp", action="store_true", help="Skip MCP gateway, use direct Jira REST API")
    parser.add_argument("--jira-url", default=None, help=f"Jira base URL (default: {DEFAULT_JIRA_URL})")
    parser.add_argument("--jira-token", default=None, help="Jira PAT (prefer JIRA_TOKEN env var instead)")
    args = parser.parse_args()

    config = parse_config(args.config)
    sprint_name = config.sprint_name
    if not sprint_name:
        print("Error: no sprint name in config.", file=sys.stderr)
        sys.exit(1)

    safe_name = sprint_name.replace(" ", "_")
    output_path = Path(args.output) if args.output else Path(f"sprint_data_{safe_name}.json")

    # ── Try MCP gateway first ────────────────────────────────────────────
    if not args.no_mcp:
        mcp_path = Path(args.mcp_config) if args.mcp_config else find_mcp_config()
        if mcp_path and mcp_path.exists():
            mcp_result = load_jira_mcp_config(mcp_path)
            if mcp_result:
                mcp_url, mcp_headers = mcp_result
                print(f"Mode: MCP gateway ({mcp_url})")
                try:
                    fetch_via_mcp(
                        mcp_url, mcp_headers, sprint_name, args.board_id, output_path,
                        jira_url=args.jira_url, jira_token=args.jira_token,
                    )
                    return
                except Exception as e:
                    print(f"\nMCP gateway failed: {e}", file=sys.stderr)
                    print("Falling back to direct Jira REST API...\n")

    # ── Fallback: direct REST API ────────────────────────────────────────
    base_url = resolve_jira_url(args.jira_url)
    print(f"Mode: Direct Jira REST API ({base_url})")
    pat = resolve_jira_pat(args.jira_token)
    fetch_via_rest(base_url, pat, sprint_name, args.board_id, output_path)


if __name__ == "__main__":
    main()

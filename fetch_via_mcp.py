#!/usr/bin/env python3
"""
Fetch sprint data from Jira and export to portable JSON.

Supports two modes (auto-detected):
  1. MCP gateway  — optional legacy Silabs gateway via ~/.cursor/mcp.json
  2. Direct REST  — Silabs Server/DC or Atlassian Cloud via .env / Settings keys

Prefer ``--no-mcp`` (or unset jira-mcp) for Cloud. REST auth is selected by
``JIRA_BACKEND=server|cloud`` (see ``jira_auth.py``).

Usage
-----
    # Force direct REST (recommended)
    python fetch_via_mcp.py --config sprint_report_config.md --no-mcp

    # Cloud example
    JIRA_BACKEND=cloud JIRA_BASE_URL=https://siliconlabs.atlassian.net \\
      JIRA_USER=you@silabs.com JIRA_TOKEN=api-token \\
      python fetch_via_mcp.py --config sprint_report_config.md --no-mcp
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
from jira_auth import (
    BACKEND_CLOUD,
    BACKEND_SERVER,
    DEFAULT_URLS,
    JiraAuthError,
    build_auth,
    credentials_from_environ,
    normalize_backend,
)
from mcp_client import McpClient, find_mcp_config, load_mcp_server_config
from utils import (
    classify_issue_bucket,
    derive_issue_added_to_sprint,
    extract_issuetype_info,
    extract_story_points,
    issue_has_subtasks,
    jira_issue_is_rest_api_shape,
    parse_jira_time_to_hours,
    sprint_issue_fields,
)


DEFAULT_JIRA_URL = DEFAULT_URLS[BACKEND_SERVER]
SPRINT_FIELDS_REST = sprint_issue_fields(BACKEND_SERVER)
SPRINT_FIELDS_MCP = (
    sprint_issue_fields(BACKEND_SERVER).replace("resolutiondate,", "resolutiondate,story_points,")
)


# ── Direct Jira REST Client ─────────────────────────────────────────────────

class JiraRestClient:
    """Direct Jira REST API client (Server Bearer PAT or Cloud Basic)."""

    def __init__(self, base_url: str, auth: AuthBase, backend: str = BACKEND_SERVER):
        self.base_url = base_url.rstrip("/")
        self.backend = normalize_backend(backend)
        self.session = requests.Session()
        self.session.auth = auth
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

    def get_sprint_issues(self, sprint_id: int, fields: str | None = None) -> list[dict]:
        field_list = fields if fields is not None else sprint_issue_fields(self.backend)
        all_issues = []
        start_at = 0
        while True:
            params = {"fields": field_list, "startAt": start_at, "maxResults": 50}
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

    def get_issue_changelog(self, issue_key: str) -> list[dict]:
        data = self._get(
            f"/rest/api/2/issue/{issue_key}",
            {"expand": "changelog", "fields": "summary"},
        )
        return (data.get("changelog") or {}).get("histories", [])


# ── Shared data conversion ──────────────────────────────────────────────────

def convert_issue_mcp(raw: dict, backend: str | None = None) -> dict:
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
        "story_points": extract_story_points(raw, backend=backend),
        "resolution_date": resolution_date,
        "parent_key": (raw.get("parent") or {}).get("key"),
    }


def convert_issue_rest(raw: dict, backend: str | None = None) -> dict:
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
        "story_points": extract_story_points(fields, backend=backend),
        "resolution_date": resolution_date,
        "parent_key": parent.get("key") if parent else None,
    }


def convert_issue_auto(raw: dict, backend: str | None = None) -> dict:
    """Use REST or flattened MCP mapping depending on how Jira/MCP returned the issue."""
    if jira_issue_is_rest_api_shape(raw):
        return convert_issue_rest(raw, backend=backend)
    return convert_issue_mcp(raw, backend=backend)


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


def _load_credential_env_files() -> None:
    script_dir = Path(__file__).resolve().parent
    load_env_file(script_dir / ".env")
    load_env_file(script_dir.parent / ".env")
    load_env_file(script_dir / ".env.defaults")


def resolve_rest_creds(
    jira_url: str | None = None,
    jira_token: str | None = None,
    jira_user: str | None = None,
    jira_backend: str | None = None,
    *,
    interactive: bool = True,
) -> dict[str, str]:
    """Merge CLI overrides with env / .env into a credentials dict for ``build_auth``."""
    _load_credential_env_files()
    creds = credentials_from_environ()
    if jira_backend:
        creds["JIRA_BACKEND"] = jira_backend
    if jira_url:
        creds["JIRA_BASE_URL"] = jira_url
    if jira_token:
        creds["JIRA_TOKEN"] = jira_token
    if jira_user:
        creds["JIRA_USER"] = jira_user

    if not (creds.get("JIRA_TOKEN") or "").strip():
        mcp_path = find_mcp_config()
        if mcp_path:
            pat = extract_pat_from_mcp_config(mcp_path)
            if pat:
                print(f"  Using Jira PAT extracted from {mcp_path}")
                creds["JIRA_TOKEN"] = pat
                if not (creds.get("JIRA_BACKEND") or "").strip():
                    creds["JIRA_BACKEND"] = BACKEND_SERVER

    try:
        normalize_backend(creds.get("JIRA_BACKEND"))
        build_auth(creds)
        return creds
    except JiraAuthError:
        pass

    if not interactive:
        raise JiraAuthError("Jira credentials not configured.")

    backend = normalize_backend(creds.get("JIRA_BACKEND") or BACKEND_SERVER)
    print()
    print(f"  Incomplete credentials for backend '{backend}'.")
    if not (creds.get("JIRA_BASE_URL") or "").strip():
        default = DEFAULT_URLS[backend]
        entered = input(f"  Jira base URL [{default}]: ").strip()
        creds["JIRA_BASE_URL"] = entered or default
    if backend == BACKEND_CLOUD and not (creds.get("JIRA_USER") or "").strip():
        creds["JIRA_USER"] = input("  Atlassian account email: ").strip()
    if not (creds.get("JIRA_TOKEN") or "").strip():
        label = "API token" if backend == BACKEND_CLOUD else "Jira PAT"
        creds["JIRA_TOKEN"] = getpass.getpass(f"  Enter {label}: ").strip()
    try:
        build_auth(creds)
    except JiraAuthError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    return creds


def resolve_jira_url(cli_arg: str | None) -> str:
    """Resolve Jira base URL with priority: CLI arg > env var > .env > .env.defaults > hardcoded."""
    if cli_arg:
        return cli_arg.rstrip("/")
    _load_credential_env_files()
    return os.environ.get("JIRA_BASE_URL", DEFAULT_JIRA_URL).rstrip("/")


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


def _make_history_client(
    jira_url: str | None,
    jira_token: str | None,
) -> JiraRestClient | None:
    try:
        creds = resolve_rest_creds(jira_url, jira_token, interactive=False)
        base_url, auth = build_auth(creds)
        backend = normalize_backend(creds.get("JIRA_BACKEND"))
    except JiraAuthError:
        return None
    return JiraRestClient(base_url, auth, backend=backend)


def _enrich_issues_with_backlog_churn(
    issues: list[dict],
    history_client: JiraRestClient | None,
    sprint_name: str,
    sprint_start: str,
) -> None:
    if not issues or history_client is None:
        return
    print(
        f"Fetching issue history for {len(issues)} tickets (backlog churn)...",
        end="",
        flush=True,
    )
    for idx, issue in enumerate(issues):
        key = issue.get("key", "")
        histories = history_client.get_issue_changelog(key)
        issue.update(
            derive_issue_added_to_sprint(
                sprint_name=sprint_name,
                sprint_start=sprint_start,
                changelog_histories=histories,
            )
        )
        if (idx + 1) % 5 == 0:
            print(f" {idx + 1}/{len(issues)}", end="", flush=True)
    print(" done.")


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
    sprint_start_raw = sprint.get("start_date") or sprint.get("startDate", "")
    start_date = sprint_start_raw[:10]
    sprint_end_raw = sprint.get("end_date") or sprint.get("endDate", "")
    end_date = sprint_end_raw[:10]
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

    issues = [convert_issue_auto(i, backend=BACKEND_SERVER) for i in all_raw_issues]

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

    history_client = _make_history_client(jira_url, jira_token)
    _enrich_issues_with_backlog_churn(
        issues,
        history_client,
        sprint_name,
        sprint_start_raw or start_date,
    )

    _write_output(
        sprint_name,
        start_date,
        end_date,
        goal,
        issues,
        worklogs,
        tickets_to_fetch,
        output_path,
        start_datetime=sprint_start_raw,
        end_datetime=sprint_end_raw,
    )


# ── Fetch via direct REST ───────────────────────────────────────────────────

def fetch_via_rest(
    base_url: str,
    auth: AuthBase,
    sprint_name: str,
    board_id: int | None,
    output_path: Path,
    backend: str = BACKEND_SERVER,
):
    """Fetch sprint data using direct Jira REST API."""
    backend = normalize_backend(backend)
    print(f"Connecting to Jira REST API at {base_url} (backend={backend})...")
    client = JiraRestClient(base_url, auth, backend=backend)

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
    sprint_start_raw = sprint.get("startDate") or sprint.get("start_date", "")
    start_date = sprint_start_raw[:10]
    sprint_end_raw = sprint.get("endDate") or sprint.get("end_date", "")
    end_date = sprint_end_raw[:10]
    goal = sprint.get("goal", "")
    print(f"Found: {sprint_name} (ID: {sprint_id}, {start_date} → {end_date})")

    print("Fetching issues...", end="", flush=True)
    all_raw_issues = client.get_sprint_issues(sprint_id)
    print(f" {len(all_raw_issues)} done.")

    issues = [convert_issue_rest(i, backend=backend) for i in all_raw_issues]

    tickets_to_fetch = [i["key"] for i in issues]
    print(f"Fetching worklogs for {len(tickets_to_fetch)} tickets...", end="", flush=True)
    worklogs: dict[str, list[dict]] = {}
    for idx, key in enumerate(tickets_to_fetch):
        raw_wl = client.get_worklogs(key)
        worklogs[key] = [convert_worklog_rest(wl) for wl in raw_wl]
        if (idx + 1) % 5 == 0:
            print(f" {idx + 1}/{len(tickets_to_fetch)}", end="", flush=True)
    print(" done.")

    _enrich_issues_with_backlog_churn(
        issues,
        client,
        sprint_name,
        sprint_start_raw or start_date,
    )

    _write_output(
        sprint_name,
        start_date,
        end_date,
        goal,
        issues,
        worklogs,
        tickets_to_fetch,
        output_path,
        start_datetime=sprint_start_raw,
        end_datetime=sprint_end_raw,
    )


# ── Shared output ───────────────────────────────────────────────────────────

def _write_output(
    sprint_name,
    start_date,
    end_date,
    goal,
    issues,
    worklogs,
    tickets_to_fetch,
    output_path,
    *,
    start_datetime: str = "",
    end_datetime: str = "",
):
    data = {
        "sprint": {
            "name": sprint_name,
            "start_date": start_date,
            "end_date": end_date,
            "start_datetime": start_datetime,
            "end_datetime": end_datetime,
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
    parser.add_argument("--jira-token", default=None, help="Jira token (prefer JIRA_TOKEN env var)")
    parser.add_argument("--jira-user", default=None, help="Email/username (required for Cloud)")
    parser.add_argument(
        "--jira-backend",
        default=None,
        choices=[BACKEND_SERVER, BACKEND_CLOUD],
        help="server (Silabs Bearer PAT) or cloud (Atlassian Basic email+token)",
    )
    args = parser.parse_args()

    config = parse_config(args.config)
    sprint_name = config.sprint_name
    if not sprint_name:
        print("Error: no sprint name in config.", file=sys.stderr)
        sys.exit(1)

    safe_name = sprint_name.replace(" ", "_")
    output_path = Path(args.output) if args.output else Path(f"sprint_data_{safe_name}.json")

    # ── Try MCP gateway first (legacy Silabs gateway only) ───────────────
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

    # ── Fallback: direct REST API (Server or Cloud) ──────────────────────
    creds = resolve_rest_creds(
        args.jira_url,
        args.jira_token,
        args.jira_user,
        args.jira_backend,
        interactive=True,
    )
    base_url, auth = build_auth(creds)
    backend = normalize_backend(creds.get("JIRA_BACKEND"))
    print(f"Mode: Direct Jira REST API ({base_url}, backend={backend})")
    fetch_via_rest(
        base_url, auth, sprint_name, args.board_id, output_path, backend=backend,
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Fetch sprint data from Jira REST API and export to portable JSON.

This script replaces the AI agent for data collection. It:
  1. Reads sprint_report_config.md to get the sprint name and team
  2. Finds the matching sprint on the Jira board
  3. Fetches all issues in the sprint
  4. Fetches worklogs for each issue
  5. Writes sprint_data_<name>.json

Authentication
--------------
Set these environment variables (or put them in a .env file):

    export JIRA_BASE_URL="https://jira.silabs.com"
    export JIRA_TOKEN="your-personal-access-token"

    # --- OR use basic auth ---
    export JIRA_BASE_URL="https://jira.silabs.com"
    export JIRA_USER="your-username"
    export JIRA_PASSWORD="your-password"

To create a personal access token in Jira:
  Profile → Personal Access Tokens → Create token

Usage
-----
    # Using config file (reads sprint name, team from config)
    python fetch_sprint_data.py --config ../sprint_report_config.md

    # Override output path
    python fetch_sprint_data.py --config ../sprint_report_config.md -o my_sprint.json

    # Specify board ID directly (skips board search)
    python fetch_sprint_data.py --config ../sprint_report_config.md --board-id 1325

    # Load env from .env file
    python fetch_sprint_data.py --config ../sprint_report_config.md --env-file ../.env
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_parser import parse_config
from utils import parse_jira_time_to_hours


# ── Jira REST client ────────────────────────────────────────────────────────

class JiraClient:
    def __init__(self, base_url: str, auth):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = auth
        self.session.headers.update({"Content-Type": "application/json"})

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def find_boards(self, name: str, board_type: str = "scrum") -> list[dict]:
        """Search for agile boards by name."""
        params = {"type": board_type, "name": name, "maxResults": 20}
        data = self._get("/rest/agile/1.0/board", params)
        return data.get("values", [])

    def get_sprints(self, board_id: int, state: str | None = None) -> list[dict]:
        """Get sprints from a board, optionally filtered by state."""
        params = {"maxResults": 50}
        if state:
            params["state"] = state
        data = self._get(f"/rest/agile/1.0/board/{board_id}/sprint", params)
        return data.get("values", [])

    def get_sprint_issues(
        self, sprint_id: int, fields: str = "summary,status,issuetype,assignee,timetracking,parent,subtasks",
        max_results: int = 200,
    ) -> list[dict]:
        """Fetch all issues in a sprint (handles pagination)."""
        all_issues = []
        start_at = 0
        while True:
            params = {"fields": fields, "startAt": start_at, "maxResults": min(50, max_results - start_at)}
            data = self._get(f"/rest/agile/1.0/sprint/{sprint_id}/issue", params)
            issues = data.get("issues", [])
            all_issues.extend(issues)
            if start_at + len(issues) >= data.get("total", 0) or not issues:
                break
            start_at += len(issues)
        return all_issues

    def get_worklogs(self, issue_key: str) -> list[dict]:
        """Fetch all worklog entries for an issue."""
        data = self._get(f"/rest/api/2/issue/{issue_key}/worklog")
        return data.get("worklogs", [])


# ── Data conversion ─────────────────────────────────────────────────────────

def classify_issue(raw: dict) -> str:
    fields = raw.get("fields", {})
    has_parent = fields.get("parent") is not None
    subtasks = fields.get("subtasks", [])
    has_subtasks = bool(subtasks) and len(subtasks) > 0
    if has_subtasks and not has_parent:
        return "Parent"
    if has_parent:
        return "Sub-task"
    return "Standalone"


def convert_issue(raw: dict) -> dict:
    fields = raw.get("fields", {})
    tt = fields.get("timetracking", {}) or {}
    est_raw = tt.get("originalEstimate", "0") or "0"
    rem_raw = tt.get("remainingEstimate", "0") or "0"
    assignee = fields.get("assignee") or {}
    status = fields.get("status", {})
    parent = fields.get("parent")

    return {
        "key": raw["key"],
        "summary": fields.get("summary", ""),
        "status": status.get("name", "Unknown"),
        "status_category": status.get("statusCategory", {}).get("name", "Unknown"),
        "type": classify_issue(raw),
        "assignee": assignee.get("displayName", "Unassigned"),
        "estimate_hours": parse_jira_time_to_hours(est_raw),
        "estimate_raw": est_raw,
        "remaining_estimate_hours": parse_jira_time_to_hours(rem_raw),
        "remaining_estimate_raw": rem_raw,
        "parent_key": parent.get("key") if parent else None,
    }


def convert_worklog(raw: dict) -> dict:
    started = raw.get("started", "")[:10]
    author_obj = raw.get("author", {})
    author_name = author_obj.get("displayName", "Unknown")
    return {
        "started": started,
        "seconds": raw.get("timeSpentSeconds", 0),
        "author": author_name,
    }


# ── Main logic ──────────────────────────────────────────────────────────────

def load_env_file(path: str):
    """Load KEY=VALUE pairs from a .env file into os.environ."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            value = value.strip().strip("'\"")
            os.environ.setdefault(key.strip(), value)


def build_auth():
    """Build requests auth from environment variables."""
    base_url = os.environ.get("JIRA_BASE_URL")
    if not base_url:
        print("Error: JIRA_BASE_URL not set.", file=sys.stderr)
        print("Set it via environment variable or .env file.", file=sys.stderr)
        sys.exit(1)

    token = os.environ.get("JIRA_TOKEN")
    if token:
        class BearerAuth(requests.auth.AuthBase):
            def __init__(self, t):
                self.token = t
            def __call__(self, r):
                r.headers["Authorization"] = f"Bearer {self.token}"
                return r
        return base_url, BearerAuth(token)

    user = os.environ.get("JIRA_USER")
    password = os.environ.get("JIRA_PASSWORD")
    if user and password:
        return base_url, HTTPBasicAuth(user, password)

    print("Error: No Jira credentials found.", file=sys.stderr)
    print("Set JIRA_TOKEN or JIRA_USER + JIRA_PASSWORD.", file=sys.stderr)
    sys.exit(1)


def find_sprint(client: JiraClient, board_id: int, sprint_name: str) -> dict | None:
    """Search active, then future, then closed sprints for a name match."""
    all_found = []
    for state in ["active", "future", "closed"]:
        sprints = client.get_sprints(board_id, state=state)
        for s in sprints:
            all_found.append(s)
            if s.get("name") == sprint_name:
                return s

    print(f"\n  Sprint '{sprint_name}' not found. Sprints on this board:", file=sys.stderr)
    for s in all_found[:20]:
        print(f"    - {s.get('name')} [{s.get('state')}]", file=sys.stderr)
    if len(all_found) > 20:
        print(f"    ... and {len(all_found) - 20} more", file=sys.stderr)
    return None


def find_board(client: JiraClient, hint: str) -> dict | None:
    """
    Find a board using progressively shorter keyword prefixes from the
    sprint name.  Strips trailing version/number tokens first
    (e.g., "Wi-Fi_LMAC_2026_4" → search for "Wi-Fi LMAC").

    Among multiple matches, prefers:
      1. Boards whose name starts with the search term (closest match)
      2. Shorter board names (less likely to be a sub-team variant)
      3. Non-"Copy" boards
    """
    keywords = hint.replace("_", " ").split()

    # Drop trailing numeric-only tokens (year, sprint number)
    while keywords and keywords[-1].isdigit():
        keywords.pop()

    if not keywords:
        keywords = hint.replace("_", " ").split()

    search_terms = []
    for i in range(len(keywords), 0, -1):
        search_terms.append(" ".join(keywords[:i]))

    all_boards_seen = []
    for term in search_terms:
        boards = client.find_boards(term)
        # Filter out copies
        candidates = [b for b in boards if "copy" not in b.get("name", "").lower()]
        all_boards_seen.extend(boards)

        if not candidates:
            continue

        # Score: prefer name starting with search term, then shortest name
        def score(b):
            name = b.get("name", "")
            starts_with = name.lower().startswith(term.lower())
            return (not starts_with, len(name))

        candidates.sort(key=score)
        best = candidates[0]
        print(f"  Matched '{term}' → {best['name']} (ID: {best['id']})")
        return best

    if all_boards_seen:
        print(f"\n  No primary board found. Boards matching search:", file=sys.stderr)
        seen_ids = set()
        for b in all_boards_seen:
            if b["id"] not in seen_ids:
                seen_ids.add(b["id"])
                print(f"    - [{b['id']}] {b['name']} ({b.get('type', '?')})", file=sys.stderr)
        print(f"\n  Use --board-id <ID> to pick the right one.", file=sys.stderr)
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Fetch sprint data from Jira and export to JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", "-c", required=True, help="Path to sprint_report_config.md")
    parser.add_argument("--output", "-o", default=None, help="Output JSON path (default: sprint_data_<name>.json)")
    parser.add_argument("--board-id", type=int, default=None, help="Jira board ID (skips board search)")
    parser.add_argument("--env-file", default=None, help="Path to .env file with JIRA_BASE_URL, JIRA_TOKEN, etc.")
    args = parser.parse_args()

    # Load env
    if args.env_file:
        load_env_file(args.env_file)
    else:
        for candidate in [".env", "../.env"]:
            if Path(candidate).exists():
                load_env_file(candidate)
                break

    config = parse_config(args.config)
    sprint_name = config.sprint_name
    if not sprint_name:
        print("Error: no sprint name found in config.", file=sys.stderr)
        sys.exit(1)

    safe_name = sprint_name.replace(" ", "_")
    output_path = Path(args.output) if args.output else Path(f"sprint_data_{safe_name}.json")

    base_url, auth = build_auth()
    client = JiraClient(base_url, auth)
    print(f"Connected to: {base_url}")

    # ── Find board ───────────────────────────────────────────────────────
    if args.board_id:
        board_id = args.board_id
        print(f"Using board ID: {board_id}")
    else:
        print(f"Searching for board matching: {sprint_name}")
        board = find_board(client, sprint_name)
        if not board:
            print("\nError: could not find a matching board.", file=sys.stderr)
            print("Use --board-id <ID> to specify the board directly.", file=sys.stderr)
            print("You can find board IDs in Jira: Board → Board settings → URL contains boardId=<ID>", file=sys.stderr)
            sys.exit(1)
        board_id = board["id"]
        print(f"Found board: {board['name']} (ID: {board_id})")

    # ── Find sprint ──────────────────────────────────────────────────────
    print(f"Looking for sprint: {sprint_name}")
    sprint = find_sprint(client, board_id, sprint_name)
    if not sprint:
        print(f"\nError: sprint '{sprint_name}' not found on board {board_id}.", file=sys.stderr)
        print(f"Check that the sprint name in your config matches Jira exactly.", file=sys.stderr)
        print(f"If the board is wrong, re-run with: --board-id <correct_id>", file=sys.stderr)
        sys.exit(1)

    sprint_id = sprint["id"]
    start_date = sprint.get("startDate", "")[:10]
    end_date = sprint.get("endDate", "")[:10]
    goal = sprint.get("goal", "")
    print(f"Found sprint: {sprint_name} (ID: {sprint_id}, {start_date} → {end_date})")

    # ── Fetch issues ─────────────────────────────────────────────────────
    print("Fetching issues...", end="", flush=True)
    raw_issues = client.get_sprint_issues(sprint_id)
    print(f" {len(raw_issues)} issues found.")

    issues = [convert_issue(i) for i in raw_issues]

    # ── Fetch worklogs ───────────────────────────────────────────────────
    parent_keys = {i["key"] for i in issues if i["type"] == "Parent"}
    tickets_to_fetch = [i["key"] for i in issues]
    print(f"Fetching worklogs for {len(tickets_to_fetch)} tickets...", end="", flush=True)

    worklogs: dict[str, list[dict]] = {}
    for idx, key in enumerate(tickets_to_fetch):
        raw_wl = client.get_worklogs(key)
        worklogs[key] = [convert_worklog(wl) for wl in raw_wl]
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nSprint data exported to: {output_path}")
    print(f"Issues: {len(issues)} ({len(parent_keys)} parents, {len(tickets_to_fetch)} sub-tasks/standalone)")
    print(f"Worklogs: {sum(len(v) for v in worklogs.values())} entries across {len(worklogs)} tickets")
    print(f"\nNext step: python sprint_report.py -c {args.config} -d {output_path}")


if __name__ == "__main__":
    main()

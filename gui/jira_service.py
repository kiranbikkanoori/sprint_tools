"""
Programmatic wrapper around the existing Jira fetch logic.

Reuses ``JiraClient``, ``convert_issue``, ``convert_worklog`` from
``fetch_sprint_data.py`` without invoking its CLI ``main()``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

# Make sibling modules importable when running from source or PyInstaller.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fetch_sprint_data import (
    JiraClient,
    convert_issue,
    convert_worklog,
    enrich_issues_with_backlog_churn,
    find_board,
    find_sprint,
)
from jira_auth import (
    JiraAuthError,
    build_auth,
    describe_auth,
    normalize_backend,
    probe_connection,
)
from utils import parse_iso_date


class JiraConfigError(RuntimeError):
    """Missing or invalid Jira credentials."""


def make_client(creds: dict[str, str]) -> JiraClient:
    """Build a JiraClient from a credentials dict (see AppSettings.effective_credentials)."""
    try:
        base_url, auth = build_auth(creds)
        backend = normalize_backend(creds.get("JIRA_BACKEND"))
    except JiraAuthError as e:
        raise JiraConfigError(str(e)) from e
    return JiraClient(base_url, auth, backend=backend)


def test_connection(creds: dict[str, str]) -> tuple[str, int, str]:
    """
    Validate credentials against the selected backend.

    Returns ``(base_url, board_count, auth_description)``.
    """
    try:
        base_url, auth = build_auth(creds)
    except JiraAuthError as e:
        raise JiraConfigError(str(e)) from e
    result = probe_connection(base_url, auth)
    return base_url, len(result["boards"]), describe_auth(creds)


def list_boards(client: JiraClient, query: str = "") -> list[dict]:
    """Return scrum boards whose name matches ``query`` (empty = first 50)."""
    return client.find_boards(query or "", board_type="scrum")


def find_board_for_sprint(client: JiraClient, sprint_name_hint: str) -> Optional[dict]:
    """Convenience wrapper around the smart board-finder in fetch_sprint_data."""
    return find_board(client, sprint_name_hint)


def list_sprints(
    client: JiraClient, board_id: int, states: tuple[str, ...] = ("active", "future", "closed"),
) -> list[dict]:
    """Return sprints on ``board_id`` filtered by ``states`` (active first, newest last)."""
    out: list[dict] = []
    for state in states:
        out.extend(client.get_sprints(board_id, state=state))
    return out


def fetch_sprint_payload(
    client: JiraClient,
    sprint: dict,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> dict:
    """
    Fetch issues + worklogs for a sprint and return the same JSON payload
    shape that ``sprint_report.py`` consumes.

    ``progress_cb(message, current, total)`` is invoked for UI feedback.
    """
    sprint_id = sprint["id"]
    sprint_name = sprint.get("name", "")
    sprint_start_raw = sprint.get("startDate") or ""
    sprint_end_raw = sprint.get("endDate") or ""
    start_parsed = parse_iso_date(sprint_start_raw)
    end_parsed = parse_iso_date(sprint_end_raw)
    start_date = start_parsed.isoformat() if start_parsed else ""
    end_date = end_parsed.isoformat() if end_parsed else ""
    goal = sprint.get("goal", "") or ""

    if progress_cb:
        progress_cb("Fetching issues…", 0, 1)
    raw_issues = client.get_sprint_issues(sprint_id)
    issues = [convert_issue(i, backend=client.backend) for i in raw_issues]

    total = len(issues)
    worklogs: dict[str, list[dict]] = {}
    for idx, issue in enumerate(issues, start=1):
        key = issue["key"]
        if progress_cb:
            progress_cb(f"Fetching worklogs ({idx}/{total}) — {key}", idx, total)
        raw_wl = client.get_worklogs(key)
        worklogs[key] = [convert_worklog(wl) for wl in raw_wl]

    enrich_issues_with_backlog_churn(
        client,
        issues,
        sprint_name,
        sprint_start_raw or start_date,
    )

    return {
        "sprint": {
            "name": sprint_name,
            "start_date": start_date,
            "end_date": end_date,
            "start_datetime": sprint_start_raw,
            "end_datetime": sprint_end_raw,
            "goal": goal,
        },
        "issues": issues,
        "worklogs": worklogs,
    }


def assignees_in_payload(payload: dict) -> list[str]:
    """Distinct, ordered list of assignees (Unassigned filtered out)."""
    seen: list[str] = []
    for issue in payload.get("issues", []):
        name = (issue.get("assignee") or "").strip()
        if not name or name == "Unassigned":
            continue
        if name not in seen:
            seen.append(name)
    return seen


def ticket_keys_in_payload(payload: dict) -> list[str]:
    return [i.get("key", "") for i in payload.get("issues", []) if i.get("key")]

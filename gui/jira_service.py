"""
Programmatic wrapper around the existing Jira fetch logic.

Reuses ``JiraClient``, ``convert_issue``, ``convert_worklog`` from
``fetch_sprint_data.py`` without invoking its CLI ``main()``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

import requests
from requests.auth import HTTPBasicAuth

# Make sibling modules importable when running from source or PyInstaller.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fetch_sprint_data import (
    JiraClient,
    convert_issue,
    convert_worklog,
    find_board,
    find_sprint,
)


class JiraConfigError(RuntimeError):
    """Missing or invalid Jira credentials."""


class _BearerAuth(requests.auth.AuthBase):
    def __init__(self, token: str) -> None:
        self.token = token

    def __call__(self, r):
        r.headers["Authorization"] = f"Bearer {self.token}"
        return r


def make_client(creds: dict[str, str]) -> JiraClient:
    """Build a JiraClient from a credentials dict (see AppSettings.effective_credentials)."""
    base_url = creds.get("JIRA_BASE_URL", "").strip()
    if not base_url:
        raise JiraConfigError("Jira base URL is not configured.")
    token = creds.get("JIRA_TOKEN", "").strip()
    if token:
        return JiraClient(base_url, _BearerAuth(token))
    user = creds.get("JIRA_USER", "").strip()
    password = creds.get("JIRA_PASSWORD", "").strip()
    if user and password:
        return JiraClient(base_url, HTTPBasicAuth(user, password))
    raise JiraConfigError(
        "No Jira credentials configured. Set a personal access token "
        "or a username + password in Settings."
    )


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
    start_date = (sprint.get("startDate") or "")[:10]
    end_date = (sprint.get("endDate") or "")[:10]
    goal = sprint.get("goal", "") or ""

    if progress_cb:
        progress_cb("Fetching issues…", 0, 1)
    raw_issues = client.get_sprint_issues(sprint_id)
    issues = [convert_issue(i) for i in raw_issues]

    total = len(issues)
    worklogs: dict[str, list[dict]] = {}
    for idx, issue in enumerate(issues, start=1):
        key = issue["key"]
        if progress_cb:
            progress_cb(f"Fetching worklogs ({idx}/{total}) — {key}", idx, total)
        raw_wl = client.get_worklogs(key)
        worklogs[key] = [convert_worklog(wl) for wl in raw_wl]

    return {
        "sprint": {
            "name": sprint_name,
            "start_date": start_date,
            "end_date": end_date,
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

"""
Shared utility functions for sprint report tools.
"""

import re
from datetime import date, timedelta

# Whole-word "story" in Jira issue type name (e.g. "User Story", "RnD Story"; not "history").
_ISSUE_TYPE_STORY_WORD = re.compile(r"\bstory\b", re.I)

# Jira issue type names (lowercase) treated as **stories** for worklog buckets.
ISSUE_TYPE_STORY_NAMES = frozenset({
    "story",
    "user story",
    "epic",
    "feature",
    "enabler",
    "enabler story",
    "change request",
})


def extract_issuetype_info(raw: dict, *, rest_fields: dict | None = None) -> tuple[str, bool]:
    """
    Return ``(display_name, issuetype_subtask)`` from MCP- or REST-shaped issue dicts.

    Reads ``fields.issuetype`` when present, then top-level ``issuetype`` / ``issueType``.
    """
    it = None
    if rest_fields is not None:
        it = rest_fields.get("issuetype") or rest_fields.get("issueType")
    else:
        fields = raw.get("fields")
        if isinstance(fields, dict):
            it = fields.get("issuetype") or fields.get("issueType")
        if it is None:
            it = (
                raw.get("issuetype")
                or raw.get("issueType")
                or raw.get("issue_type")
                or raw.get("issueTypeName")
            )
    if isinstance(it, dict):
        name = str(it.get("name") or it.get("Name") or "").strip()
        sub = it.get("subtask")
        is_sub = bool(sub) if sub is not None else False
        return name, is_sub
    if isinstance(it, str) and it.strip():
        return it.strip(), False

    # Flattened MCP / alternate shapes: type or issueType as dict or string at issue root.
    if rest_fields is None:
        for alt_key in ("type", "issueType", "issue_type"):
            alt = raw.get(alt_key)
            if isinstance(alt, dict):
                nm = str(alt.get("name") or alt.get("Name") or "").strip()
                if nm:
                    sub = alt.get("subtask")
                    is_sub = bool(sub) if sub is not None else False
                    return nm, is_sub
            if isinstance(alt, str) and alt.strip():
                return alt.strip(), False
    return "", False


def extract_issuetype_name(raw: dict, *, rest_fields: dict | None = None) -> str:
    """Best-effort issuetype display name (see ``extract_issuetype_info``)."""
    return extract_issuetype_info(raw, rest_fields=rest_fields)[0]


def issue_has_subtasks(raw: dict, *, rest_fields: dict | None = None) -> bool:
    """True if Jira returned at least one entry in ``subtasks`` (top-level or under ``fields``)."""
    if rest_fields is not None:
        st = rest_fields.get("subtasks") or []
        return isinstance(st, list) and len(st) > 0
    st = raw.get("subtasks") or []
    if isinstance(st, list) and len(st) > 0:
        return True
    fields = raw.get("fields")
    if isinstance(fields, dict):
        st2 = fields.get("subtasks") or []
        return isinstance(st2, list) and len(st2) > 0
    return False


def classify_issue_bucket(
    *,
    issuetype_name: str | None,
    has_parent: bool,
    issuetype_is_subtask: bool = False,
    has_subtasks: bool = False,
) -> str:
    """
    Classify for sprint worklog reporting: **Story**, **Task**, or **Sub-task**.

    - **Sub-task:** parent link, or type name Sub-task, or ``issuetype.subtask`` from Jira.
    - **Story:** name in ``ISSUE_TYPE_STORY_NAMES``, or (fallback) has native sub-tasks and no parent.
    - **Task:** other non–sub-task issues.
    """
    n = (issuetype_name or "").strip().lower()
    if has_parent or n == "sub-task" or issuetype_is_subtask:
        return "Sub-task"
    if n in ISSUE_TYPE_STORY_NAMES:
        return "Story"
    if n and _ISSUE_TYPE_STORY_WORD.search(n):
        return "Story"
    if has_subtasks and not has_parent:
        return "Story"
    return "Task"


def effective_issue_type(issue: dict) -> str:
    """
    **Story** / **Task** / **Sub-task** from portable sprint JSON.

    Uses ``issuetype_name``, ``parent_key``, ``issuetype_subtask``, ``has_subtasks``.
    ``issuetype_name`` of ``Unknown`` is treated as missing. If the name is missing,
    falls back to normalized stored ``type`` when it is already **Story** or **Sub-task**,
    then to structural rules (e.g. ``has_subtasks``).
    """
    iname = (issue.get("issuetype_name") or "").strip()
    if iname.lower() == "unknown":
        iname = ""
    has_parent = bool(issue.get("parent_key"))
    is_sub = bool(issue.get("issuetype_subtask", False))
    has_subs = bool(issue.get("has_subtasks", False))

    if iname:
        return classify_issue_bucket(
            issuetype_name=iname,
            has_parent=has_parent,
            issuetype_is_subtask=is_sub,
            has_subtasks=has_subs,
        )

    legacy = normalize_stored_issue_type(issue.get("type"))
    if legacy == "Story":
        return "Story"
    if legacy == "Sub-task":
        return "Sub-task"

    base = classify_issue_bucket(
        issuetype_name=None,
        has_parent=has_parent,
        issuetype_is_subtask=is_sub,
        has_subtasks=has_subs,
    )
    # MCP sometimes omits issuetype entirely: many Silabs backlog items use story points only on stories.
    if base == "Task" and not has_parent and not is_sub:
        sp = issue.get("story_points")
        try:
            sp_val = float(sp) if sp is not None else 0.0
        except (TypeError, ValueError):
            sp_val = 0.0
        if sp_val > 0:
            return "Story"
    return base


def normalize_stored_issue_type(stored: str | None) -> str:
    """Map JSON ``type`` to Story | Task | Sub-task (legacy Parent / Standalone)."""
    t = (stored or "Task").strip()
    if t == "Parent":
        return "Story"
    if t == "Standalone":
        return "Task"
    return t


def worklog_started_date(wl: dict) -> date | None:
    """
    Parse YYYY-MM-DD from a worklog's ``started`` field.
    Returns None if missing or invalid (skips bad Jira/MCP rows safely).
    """
    raw = wl.get("started")
    if not raw:
        return None
    s = str(raw).strip()[:10]
    if len(s) < 10:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_jira_time_to_hours(time_str: str) -> float:
    """
    Parse Jira time format (e.g., '1w 2d 4h 30m') to decimal hours.
    Jira conventions: 1w = 5d, 1d = 8h.
    """
    if not time_str or time_str.strip() in ("N/A", "0", "0m", "None"):
        return 0.0
    hours = 0.0
    for part in time_str.strip().split():
        if part.endswith("w"):
            hours += float(part[:-1]) * 40
        elif part.endswith("d"):
            hours += float(part[:-1]) * 8
        elif part.endswith("h"):
            hours += float(part[:-1])
        elif part.endswith("m"):
            hours += float(part[:-1]) / 60
        elif part.endswith("s"):
            hours += float(part[:-1]) / 3600
    return hours


def hours_to_jira(h: float) -> str:
    """Convert decimal hours back to Jira-style string (e.g., '1w 2d 4h 30m')."""
    if h <= 0:
        return "0h"
    h = round(h, 2)
    w = int(h // 40)
    h_rem = h - w * 40
    d = int(h_rem // 8)
    h_rem2 = h_rem - d * 8
    hrs = int(h_rem2)
    mins = int(round((h_rem2 - hrs) * 60))
    parts = []
    if w:
        parts.append(f"{w}w")
    if d:
        parts.append(f"{d}d")
    if hrs:
        parts.append(f"{hrs}h")
    if mins:
        parts.append(f"{mins}m")
    return " ".join(parts) if parts else "0h"


def working_days_in_range(start: date, end: date) -> int:
    """Count weekday (Mon-Fri) days from start to end, inclusive."""
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def working_dates_in_range(start: date, end: date) -> list[date]:
    """List all weekday dates from start to end, inclusive."""
    dates = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates


def seconds_to_hours(s: float) -> float:
    return s / 3600.0

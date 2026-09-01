"""
Sprint config serialization.

The GUI works with a ``SprintConfig`` (defined in ``config_parser``) and:

* loads from / saves to a JSON file (``configs/<sprint>.json``)
* imports from / exports to the legacy markdown format
  (``sprint_report_config.md``) so the existing CLI tools keep working.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config_parser import (
    ExclusionEntry,
    ExtraTicket,
    LeaveEntry,
    SprintConfig,
    TeamMember,
    parse_config,
)


# ── JSON ────────────────────────────────────────────────────────────────────

def config_to_dict(cfg: SprintConfig) -> dict:
    return {
        "sprint_name": cfg.sprint_name,
        "sprint_duration_weeks": cfg.sprint_duration_weeks,
        "team_members": [asdict(m) for m in cfg.team_members],
        "meeting_days_reserved": cfg.meeting_days_reserved,
        "planned_leaves": [asdict(l) for l in cfg.planned_leaves],
        "other_exclusions": [asdict(e) for e in cfg.other_exclusions],
        "extra_tickets": [asdict(t) for t in cfg.extra_tickets],
        "excluded_tickets": list(cfg.excluded_tickets),
        "report_date": cfg.report_date,
        "show_per_ticket_details": cfg.show_per_ticket_details,
    }


def dict_to_config(data: dict) -> SprintConfig:
    cfg = SprintConfig()
    cfg.sprint_name = data.get("sprint_name", "") or ""
    cfg.sprint_duration_weeks = int(data.get("sprint_duration_weeks", 2) or 2)
    cfg.meeting_days_reserved = float(data.get("meeting_days_reserved", 1.0) or 0.0)
    cfg.report_date = data.get("report_date", "") or ""
    cfg.show_per_ticket_details = bool(data.get("show_per_ticket_details", True))

    cfg.team_members = [
        TeamMember(
            name=m.get("name", "").strip(),
            role=m.get("role", "").strip(),
            included=bool(m.get("included", True)),
        )
        for m in (data.get("team_members") or [])
        if m.get("name", "").strip()
    ]
    cfg.planned_leaves = [
        LeaveEntry(
            name=l.get("name", "").strip(),
            days=float(l.get("days", 0) or 0),
            notes=l.get("notes", "") or "",
        )
        for l in (data.get("planned_leaves") or [])
        if l.get("name", "").strip()
    ]
    cfg.other_exclusions = [
        ExclusionEntry(
            name=e.get("name", "").strip(),
            hours=float(e.get("hours", 0) or 0),
            reason=e.get("reason", "") or "",
        )
        for e in (data.get("other_exclusions") or [])
        if e.get("name", "").strip()
    ]
    cfg.extra_tickets = [
        ExtraTicket(
            key=t.get("key", "").strip(),
            assignee=t.get("assignee", "") or "",
            notes=t.get("notes", "") or "",
        )
        for t in (data.get("extra_tickets") or [])
        if t.get("key", "").strip()
    ]
    cfg.excluded_tickets = [
        str(k).strip() for k in (data.get("excluded_tickets") or []) if str(k).strip()
    ]
    return cfg


def save_json(cfg: SprintConfig, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config_to_dict(cfg), indent=2), encoding="utf-8")


def load_json(path: Path) -> SprintConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return dict_to_config(data)


# ── Board roster (survives sprints with no tickets for a person) ───────────

def board_roster_path(configs_root: Path, board_id: int) -> Path:
    return Path(configs_root) / f"board_{int(board_id)}_roster.json"


def load_board_roster(configs_root: Path, board_id: int) -> list[TeamMember]:
    """Return the last saved team roster for this board (may be empty)."""
    if not board_id:
        return []
    path = board_roster_path(configs_root, board_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    members: list[TeamMember] = []
    for m in data.get("team_members") or []:
        name = (m.get("name") or "").strip()
        if not name:
            continue
        members.append(
            TeamMember(
                name=name,
                role=(m.get("role") or "").strip() or "Developer",
                included=bool(m.get("included", True)),
            )
        )
    return members


def save_board_roster(configs_root: Path, board_id: int, members: list[TeamMember]) -> None:
    """Persist Include-aware team list for the board (used on next sprint load)."""
    if not board_id:
        return
    path = board_roster_path(configs_root, board_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "board_id": int(board_id),
        "team_members": [
            {
                "name": m.name.strip(),
                "role": (m.role or "").strip() or "Developer",
                "included": bool(m.included),
            }
            for m in members
            if m.name.strip()
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_recent_team_fallback(configs_root: Path) -> list[TeamMember]:
    """
    When no board roster exists yet, reuse team members from the most recently
    saved sprint config (helps first load after upgrade / new board).
    """
    root = Path(configs_root)
    if not root.is_dir():
        return []
    candidates = sorted(
        (p for p in root.glob("*.json") if not p.name.startswith("board_")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in candidates[:8]:
        try:
            cfg = load_json(path)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            continue
        if cfg.team_members:
            return list(cfg.team_members)
    return []


def team_names_from_related_sprint_configs(
    configs_root: Path, assignees: list[str]
) -> set[str]:
    """
    Names from saved sprint configs whose team overlaps current assignees.

    Used to carry leave-only / no-ticket teammates across sprints on the same
    board without merging an entire shared board roster (which can pull in
    people from unrelated teams that use the same Jira board).
    """
    anchor = {(a or "").strip() for a in assignees if (a or "").strip()}
    if not anchor:
        return set()
    root = Path(configs_root)
    if not root.is_dir():
        return set()
    names: set[str] = set()
    for path in root.glob("*.json"):
        if path.name.startswith("board_"):
            continue
        try:
            cfg = load_json(path)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            continue
        cfg_names = {(m.name or "").strip() for m in cfg.team_members if (m.name or "").strip()}
        if cfg_names & anchor:
            names |= cfg_names
    return names


def merge_team_members(*groups: list[TeamMember]) -> list[TeamMember]:
    """
    Merge team lists in priority order: earlier groups win on name collision
    for role/included; later groups only add missing names.
    """
    by_name: dict[str, TeamMember] = {}
    order: list[str] = []
    for group in groups:
        for m in group:
            name = (m.name or "").strip()
            if not name:
                continue
            if name not in by_name:
                by_name[name] = TeamMember(
                    name=name,
                    role=(m.role or "").strip() or "Developer",
                    included=bool(m.included),
                )
                order.append(name)
    return [by_name[n] for n in order]


# ── Markdown export (subset of fields the parser knows about) ──────────────

_MD_HEADER = """# Sprint Report Configuration

Generated by Sprint Report GUI. The fields below are consumed by
`sprint_report.py` / `fetch_sprint_data.py`.

---

"""


def _bool_to_md(value: bool) -> str:
    return "Yes" if value else "No"


def config_to_markdown(cfg: SprintConfig) -> str:
    out: list[str] = [_MD_HEADER.rstrip(), ""]

    out += [
        "## Sprint Details",
        "",
        f"- **Sprint Name**: `{cfg.sprint_name}`",
        f"- **Sprint Duration (weeks)**: `{cfg.sprint_duration_weeks}`",
        "",
        "---",
        "",
    ]

    out += ["## Team Members", "", "| # | Name | Role | Include in Report |", "| - | ---- | ---- | ----------------- |"]
    for i, m in enumerate(cfg.team_members, 1):
        out.append(f"| {i} | {m.name} | {m.role} | {_bool_to_md(m.included)} |")
    if not cfg.team_members:
        out.append("|   |      |      |                   |")
    out += ["", "---", ""]

    out += [
        "## Capacity Adjustments",
        "",
        "### Time Reserved for Meetings/Ceremonies (per person per sprint)",
        "",
        f"- **Days reserved**: `{cfg.meeting_days_reserved:g}`",
        "",
        "### Planned Leaves",
        "",
        "| Name | Leave Days | Notes |",
        "| ---- | ---------- | ----- |",
    ]
    for l in cfg.planned_leaves:
        out.append(f"| {l.name} | {l.days:g} | {l.notes} |")
    if not cfg.planned_leaves:
        out.append("|      |            |       |")
    out += ["", "### Other Non-Development Activities (per person)", "",
            "| Name | Hours Excluded | Reason |", "| ---- | -------------- | ------ |"]
    for e in cfg.other_exclusions:
        out.append(f"| {e.name} | {e.hours:g} | {e.reason} |")
    if not cfg.other_exclusions:
        out.append("|      |                |        |")
    out += ["", "---", ""]

    out += ["## Extra Tickets", "", "| Ticket Key | Assignee | Notes |",
            "| ---------- | -------- | ----- |"]
    for t in cfg.extra_tickets:
        out.append(f"| {t.key} | {t.assignee} | {t.notes} |")
    if not cfg.extra_tickets:
        out.append("|            |          |       |")
    out += ["", "---", ""]

    out += ["## Tickets to Exclude", "", "| Ticket Key | Reason |",
            "| ---------- | ------ |"]
    for k in cfg.excluded_tickets:
        out.append(f"| {k} |  |")
    if not cfg.excluded_tickets:
        out.append("|            |        |")
    out += ["", "---", ""]

    out += [
        "## Report Options",
        "",
        f"- **Report Date** (calculate logged work up to this date, leave blank for today): `{cfg.report_date}`",
        f"- **Show per-ticket worklog details**: `{_bool_to_md(cfg.show_per_ticket_details)}`",
        "",
    ]

    return "\n".join(out) + "\n"


def save_markdown(cfg: SprintConfig, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config_to_markdown(cfg), encoding="utf-8")


def load_markdown(path: Path) -> SprintConfig:
    return parse_config(path)

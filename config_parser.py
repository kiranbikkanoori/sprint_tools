"""
Parser for sprint_report_config.md files.
Extracts sprint settings, team members, capacity adjustments, and report options.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TeamMember:
    name: str
    role: str
    included: bool


@dataclass
class LeaveEntry:
    name: str
    days: float
    notes: str = ""


@dataclass
class ExclusionEntry:
    name: str
    hours: float
    reason: str = ""


@dataclass
class ExtraTicket:
    key: str
    assignee: str
    notes: str = ""


@dataclass
class SprintConfig:
    sprint_name: str = ""
    sprint_duration_weeks: int = 2
    team_members: list = field(default_factory=list)
    meeting_days_reserved: float = 1.0
    planned_leaves: list = field(default_factory=list)
    other_exclusions: list = field(default_factory=list)
    extra_tickets: list = field(default_factory=list)
    excluded_tickets: list = field(default_factory=list)
    report_date: str = ""
    exclude_parent_estimates: bool = True
    show_per_ticket_details: bool = True
    show_daily_log_gaps: bool = True


def _parse_inline_code(text: str) -> str:
    """Extract value from markdown inline code like `value`."""
    match = re.search(r"`([^`]*)`", text)
    return match.group(1).strip() if match else ""


def _parse_bool(text: str) -> bool:
    return text.strip().lower() in ("yes", "true", "1")


def _parse_table_rows(lines: list[str]) -> list[list[str]]:
    """Parse markdown table rows, skipping the header row and separator."""
    rows = []
    header_skipped = False
    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r"^\|[\s\-:|]+\|$", line):
            header_skipped = True
            continue
        if not header_skipped:
            # First row before the separator is the header — skip it
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if any(c for c in cells):
            rows.append(cells)
    return rows


def parse_config(config_path: str | Path) -> SprintConfig:
    """Parse a sprint_report_config.md file and return a SprintConfig."""
    config_path = Path(config_path)
    text = config_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    cfg = SprintConfig()
    current_section = ""
    current_subsection = ""
    section_lines: dict[str, list[str]] = {}

    for line in lines:
        if line.startswith("## "):
            current_section = line[3:].strip()
            current_subsection = ""
            section_lines.setdefault(current_section, [])
        elif line.startswith("### "):
            current_subsection = line[4:].strip()
            key = f"{current_section} > {current_subsection}"
            section_lines.setdefault(key, [])
        else:
            key = (
                f"{current_section} > {current_subsection}"
                if current_subsection
                else current_section
            )
            if key:
                section_lines.setdefault(key, []).append(line)

    # Sprint Details
    for line in section_lines.get("Sprint Details", []):
        if "Sprint Name" in line:
            cfg.sprint_name = _parse_inline_code(line)
        elif "Sprint Duration" in line:
            val = _parse_inline_code(line)
            cfg.sprint_duration_weeks = int(val) if val else 2

    # Team Members
    team_rows = _parse_table_rows(section_lines.get("Team Members", []))
    for row in team_rows:
        if len(row) >= 4:
            name = row[1].strip()
            role = row[2].strip()
            included = row[3].strip().lower() in ("yes", "true")
            if name:
                cfg.team_members.append(TeamMember(name=name, role=role, included=included))

    # Meeting reserve
    for line in section_lines.get(
        "Capacity Adjustments > Time Reserved for Meetings/Ceremonies (per person per sprint)",
        [],
    ):
        if "Days reserved" in line:
            val = _parse_inline_code(line)
            cfg.meeting_days_reserved = float(val) if val else 1.0

    # Planned Leaves
    leave_rows = _parse_table_rows(
        section_lines.get("Capacity Adjustments > Planned Leaves", [])
    )
    for row in leave_rows:
        if len(row) >= 2:
            name = row[0].strip()
            days_str = row[1].strip()
            notes = row[2].strip() if len(row) > 2 else ""
            if name and days_str:
                try:
                    cfg.planned_leaves.append(
                        LeaveEntry(name=name, days=float(days_str), notes=notes)
                    )
                except ValueError:
                    pass

    # Other exclusions
    excl_rows = _parse_table_rows(
        section_lines.get(
            "Capacity Adjustments > Other Non-Development Activities (per person)", []
        )
    )
    for row in excl_rows:
        if len(row) >= 2:
            name = row[0].strip()
            hours_str = row[1].strip()
            reason = row[2].strip() if len(row) > 2 else ""
            if name and hours_str:
                try:
                    cfg.other_exclusions.append(
                        ExclusionEntry(name=name, hours=float(hours_str), reason=reason)
                    )
                except ValueError:
                    pass

    # Extra Tickets
    extra_rows = _parse_table_rows(section_lines.get("Extra Tickets", []))
    for row in extra_rows:
        if len(row) >= 1:
            key = row[0].strip()
            assignee = row[1].strip() if len(row) > 1 else ""
            notes = row[2].strip() if len(row) > 2 else ""
            if key:
                cfg.extra_tickets.append(
                    ExtraTicket(key=key, assignee=assignee, notes=notes)
                )

    # Tickets to Exclude
    excl_ticket_rows = _parse_table_rows(
        section_lines.get("Tickets to Exclude", [])
    )
    for row in excl_ticket_rows:
        if len(row) >= 1 and row[0].strip():
            cfg.excluded_tickets.append(row[0].strip())

    # Report Options
    for line in section_lines.get("Report Options", []):
        if "Report Date" in line:
            cfg.report_date = _parse_inline_code(line)
        elif "Exclude parent story estimates" in line:
            cfg.exclude_parent_estimates = _parse_bool(_parse_inline_code(line))
        elif "Show per-ticket worklog details" in line:
            cfg.show_per_ticket_details = _parse_bool(_parse_inline_code(line))
        elif "Show daily log gaps" in line:
            cfg.show_daily_log_gaps = _parse_bool(_parse_inline_code(line))

    return cfg


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python config_parser.py <path_to_config.md>")
        sys.exit(1)

    cfg = parse_config(sys.argv[1])
    print(f"Sprint: {cfg.sprint_name}")
    print(f"Duration: {cfg.sprint_duration_weeks} weeks")
    print(f"Meeting reserve: {cfg.meeting_days_reserved}d")
    print(f"Team ({len(cfg.team_members)}):")
    for m in cfg.team_members:
        inc = "included" if m.included else "EXCLUDED"
        print(f"  - {m.name} ({m.role}) [{inc}]")
    print(f"Leaves: {[(l.name, l.days) for l in cfg.planned_leaves]}")
    print(f"Exclude parent estimates: {cfg.exclude_parent_estimates}")
    print(f"Show daily gaps: {cfg.show_daily_log_gaps}")

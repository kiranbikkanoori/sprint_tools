#!/usr/bin/env python3
"""
Export sprint data to a portable JSON file.

This script is run by the Cursor AI agent after it fetches data from Jira
via MCP tools.  It can also be populated manually or via Jira REST API.

The output JSON is consumed by sprint_report.py to generate the text report
and burndown chart.

Schema
------
{
  "sprint": {
    "name": "Wi-Fi_LMAC_2026_4",
    "start_date": "2026-02-18",
    "end_date": "2026-03-03",
    "goal": "optional sprint goal text"
  },
  "issues": [
    {
      "key": "RSCDEV-44099",
      "summary": "WIFI Max BSS Idle Implementation",
      "status": "In Review",
      "status_category": "In Progress",
      "type": "Sub-task",            // "Parent", "Sub-task", or "Standalone"
      "assignee": "Hemanth Reddy Narra",
      "estimate_hours": 8.0,
      "estimate_raw": "1d",
      "parent_key": "RSCDEV-28683"   // null for non-sub-tasks
    }
  ],
  "worklogs": {
    "RSCDEV-44099": [
      {
        "started": "2026-02-24",
        "seconds": 14400,
        "author": "Hemanth Reddy Narra"
      }
    ]
  }
}

Usage
-----
This file serves two purposes:

1. **Template/documentation**: Shows the exact JSON schema required by
   sprint_report.py.  Copy and fill in manually if needed.

2. **Programmatic export**: Import and call ``export_from_raw_jira()`` to
   convert raw Jira API / MCP responses into the portable format.

Examples
--------
    # From the command line (creates a template)
    python export_sprint_data.py --template -o sprint_data.json

    # From Python / agent code
    from export_sprint_data import export_from_raw_jira
    export_from_raw_jira(sprint_info, raw_issues, raw_worklogs, "sprint_data.json")
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import parse_jira_time_to_hours


def classify_issue(issue: dict) -> str:
    """Determine if a Jira issue is a Parent, Sub-task, or Standalone."""
    has_parent = issue.get("parent") is not None
    subtasks = issue.get("subtasks", [])
    has_subtasks = bool(subtasks) and len(subtasks) > 0
    if has_subtasks and not has_parent:
        return "Parent"
    if has_parent:
        return "Sub-task"
    return "Standalone"


def convert_issue(raw: dict) -> dict:
    """
    Convert a raw Jira issue (as returned by MCP jira_get_sprint_issues)
    into the portable schema.
    """
    tt = raw.get("timetracking", {}) or {}
    est_raw = tt.get("original_estimate", "0") or "0"
    rem_raw = tt.get("remaining_estimate", "0") or "0"
    assignee_obj = raw.get("assignee") or {}

    return {
        "key": raw["key"],
        "summary": raw.get("summary", ""),
        "status": raw.get("status", {}).get("name", "Unknown"),
        "status_category": raw.get("status", {}).get("category", "Unknown"),
        "type": classify_issue(raw),
        "assignee": assignee_obj.get("display_name", "Unassigned"),
        "estimate_hours": parse_jira_time_to_hours(est_raw),
        "estimate_raw": est_raw,
        "remaining_estimate_hours": parse_jira_time_to_hours(rem_raw),
        "remaining_estimate_raw": rem_raw,
        "parent_key": (raw.get("parent") or {}).get("key"),
    }


def convert_worklogs(raw_worklogs: dict[str, dict]) -> dict[str, list[dict]]:
    """
    Convert raw Jira worklog responses into the portable schema.

    Parameters
    ----------
    raw_worklogs : dict
        Mapping of ticket_key -> raw MCP worklog response
        (i.e., {"worklogs": [...]}).
    """
    result = {}
    for key, response in raw_worklogs.items():
        entries = response.get("worklogs", [])
        result[key] = []
        for wl in entries:
            started_raw = wl.get("started", "")
            started_date = started_raw[:10] if started_raw else ""
            result[key].append(
                {
                    "started": started_date,
                    "seconds": wl.get("timeSpentSeconds", 0),
                    "author": wl.get("author", "Unknown"),
                }
            )
    return result


def export_from_raw_jira(
    sprint_info: dict,
    raw_issues: list[dict],
    raw_worklogs: dict[str, dict],
    output_path: str | Path,
) -> Path:
    """
    Full pipeline: convert raw Jira data and write portable JSON.

    Parameters
    ----------
    sprint_info : dict
        Must contain: name, start_date (ISO), end_date (ISO).
        Optional: goal.
    raw_issues : list[dict]
        List of raw issue dicts from MCP ``jira_get_sprint_issues``.
    raw_worklogs : dict[str, dict]
        Mapping of ticket key -> raw MCP worklog response.
    output_path : str or Path
        Where to write the JSON.
    """
    output_path = Path(output_path)
    data = {
        "sprint": {
            "name": sprint_info["name"],
            "start_date": sprint_info["start_date"],
            "end_date": sprint_info["end_date"],
            "goal": sprint_info.get("goal", ""),
        },
        "issues": [convert_issue(i) for i in raw_issues],
        "worklogs": convert_worklogs(raw_worklogs),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Sprint data exported to: {output_path}")
    return output_path


def write_template(output_path: str | Path) -> Path:
    """Write a skeleton JSON file showing the expected schema."""
    output_path = Path(output_path)
    template = {
        "sprint": {
            "name": "Sprint_Name_Here",
            "start_date": "2026-01-01",
            "end_date": "2026-01-14",
            "goal": "Optional sprint goal",
        },
        "issues": [
            {
                "key": "PROJ-123",
                "summary": "Example ticket summary",
                "status": "In Progress",
                "status_category": "In Progress",
                "type": "Sub-task",
                "assignee": "Jane Doe",
                "estimate_hours": 16.0,
                "estimate_raw": "2d",
                "parent_key": "PROJ-100",
            }
        ],
        "worklogs": {
            "PROJ-123": [
                {
                    "started": "2026-01-02",
                    "seconds": 28800,
                    "author": "Jane Doe",
                }
            ]
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, ensure_ascii=False)
    print(f"Template written to: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Export sprint data to JSON.")
    parser.add_argument(
        "--template", action="store_true",
        help="Write a skeleton template JSON instead of converting real data.",
    )
    parser.add_argument(
        "-o", "--output", default="sprint_data.json",
        help="Output file path (default: sprint_data.json)",
    )
    args = parser.parse_args()

    if args.template:
        write_template(args.output)
    else:
        print(
            "To export real data, call export_from_raw_jira() from Python "
            "or use --template to create a skeleton.",
        )


if __name__ == "__main__":
    main()

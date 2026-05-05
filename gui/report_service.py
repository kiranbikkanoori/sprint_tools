"""
Programmatic wrapper around report + chart generation.

Mirrors the behaviour of ``sprint_report.py``'s ``main()`` but accepts an
in-memory ``SprintConfig`` and payload (instead of file paths) so the GUI
can call it directly.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config_parser import SprintConfig
from utils import effective_issue_type
from report_generator import build_sprint_work_report, generate_text_report


def generate_outputs(
    config: SprintConfig,
    payload: dict,
    output_dir: Path,
    *,
    make_report: bool = True,
    make_chart: bool = True,
) -> dict[str, Path]:
    """
    Generate the markdown report and burndown chart.

    Returns a dict with keys ``report`` and/or ``chart`` mapping to the
    written file paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sprint_info = payload["sprint"]
    sprint_start = date.fromisoformat(sprint_info["start_date"])
    sprint_end = date.fromisoformat(sprint_info["end_date"])
    sprint_goal = sprint_info.get("goal", "")
    report_date = (
        date.fromisoformat(config.report_date) if config.report_date else date.today()
    )

    issues = payload["issues"]
    worklogs = payload["worklogs"]

    work_report = build_sprint_work_report(
        config, sprint_start, sprint_end, issues, worklogs, report_date=report_date,
    )

    safe_name = (config.sprint_name or sprint_info.get("name", "sprint")).replace(" ", "_")
    written: dict[str, Path] = {}

    if make_report:
        text = generate_text_report(
            config, sprint_start, sprint_end, work_report,
            sprint_goal=sprint_goal, issues=issues,
        )
        path = output_dir / f"sprint_report_{safe_name}.md"
        path.write_text(text, encoding="utf-8")
        written["report"] = path

    if make_chart:
        from burndown_chart import generate_burndown_chart

        excluded = set(config.excluded_tickets)
        chart_keys = {
            i["key"]
            for i in issues
            if effective_issue_type(i) in ("Story", "Task")
            and i.get("key")
            and i["key"] not in excluded
        }
        chart_worklogs = {k: worklogs.get(k, []) for k in chart_keys}
        included_names = [m.name for m in config.team_members if m.included]

        path = output_dir / f"sprint_burndown_{safe_name}.png"
        generate_burndown_chart(
            sprint_name=config.sprint_name,
            sprint_start=sprint_start,
            sprint_end=sprint_end,
            member_names=included_names,
            worklogs=chart_worklogs,
            report_date=report_date,
            output_path=path,
        )
        written["chart"] = path

    return written

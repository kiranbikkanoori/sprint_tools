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
from report_html import generate_html_report
from gui.report_view_model import build_report_view_model


def generate_outputs(
    config: SprintConfig,
    payload: dict,
    output_dir: Path,
    *,
    make_report: bool = True,
    make_chart: bool = True,
) -> dict:
    """
    Generate the markdown report, styled HTML report, optional chart, and
    a structured ``view_model`` for the native Generate UI.

    Returns a dict with keys ``report``, ``report_html``, ``chart`` (paths)
    and ``view_model`` (``ReportViewModel``).
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
    written: dict = {
        "view_model": build_report_view_model(config, payload, work_report),
    }
    chart_path: Path | None = None

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

        chart_path = output_dir / f"sprint_burndown_{safe_name}.png"
        generate_burndown_chart(
            sprint_name=config.sprint_name,
            sprint_start=sprint_start,
            sprint_end=sprint_end,
            member_names=included_names,
            worklogs=chart_worklogs,
            report_date=report_date,
            output_path=chart_path,
        )
        written["chart"] = chart_path

    if make_report:
        sprint_start_raw = sprint_info.get("start_datetime") or sprint_info.get("start_date")
        text = generate_text_report(
            config, sprint_start, sprint_end, work_report,
            sprint_goal=sprint_goal,
            issues=issues,
            sprint_start_raw=sprint_start_raw,
        )
        md_path = output_dir / f"sprint_report_{safe_name}.md"
        md_path.write_text(text, encoding="utf-8")
        written["report"] = md_path

        html = generate_html_report(
            config, sprint_start, sprint_end, work_report,
            sprint_goal=sprint_goal,
            issues=issues,
            sprint_start_raw=sprint_start_raw,
            chart_path=None,
            theme=None,
            include_theme_toggle=True,
        )
        html_path = output_dir / f"sprint_report_{safe_name}.html"
        html_path.write_text(html, encoding="utf-8")
        written["report_html"] = html_path

    return written

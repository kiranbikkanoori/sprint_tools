#!/usr/bin/env python3
"""
Sprint report CLI — generates a markdown report and a stacked daily-hours chart
(story + task worklogs only; burndown line not shown).

Usage
-----
    # Full report + chart
    python sprint_report.py --config ../sprint_report_config.md --data sprint_data.json

    # Chart only
    python sprint_report.py --config ../sprint_report_config.md --data sprint_data.json --chart-only

    # Report only (no matplotlib needed)
    python sprint_report.py --config ../sprint_report_config.md --data sprint_data.json --report-only

    # Custom output directory
    python sprint_report.py --config ../sprint_report_config.md --data sprint_data.json -o ./output

    # Generate report format reference (no config/data needed)
    python sprint_report.py --generate-format
    python sprint_report.py --generate-format -o ./output
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_parser import parse_config
from utils import effective_issue_type
from report_generator import build_sprint_work_report, generate_text_report
from report_format import generate_report_format


def load_sprint_data(data_path: str | Path) -> dict:
    """Load and validate the sprint data JSON file."""
    data_path = Path(data_path)
    if not data_path.exists():
        print(f"Error: data file not found: {data_path}", file=sys.stderr)
        sys.exit(1)
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    required = {"sprint", "issues", "worklogs"}
    missing = required - set(data.keys())
    if missing:
        print(f"Error: data JSON missing keys: {missing}", file=sys.stderr)
        sys.exit(1)
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Generate sprint report and burndown chart.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config", "-c", default=None,
        help="Path to sprint_report_config.md",
    )
    parser.add_argument(
        "--data", "-d", default=None,
        help="Path to sprint data JSON (exported by export_sprint_data.py or agent)",
    )
    parser.add_argument(
        "--output-dir", "-o", default=".",
        help="Directory to write output files (default: current dir)",
    )
    parser.add_argument(
        "--report-only", action="store_true",
        help="Generate only the text report (skip chart)",
    )
    parser.add_argument(
        "--chart-only", action="store_true",
        help="Generate only the burndown chart (skip report)",
    )
    parser.add_argument(
        "--generate-format", action="store_true",
        help="Generate REPORT_FORMAT.md (field reference) and exit. No --config/--data needed.",
    )
    args = parser.parse_args()

    # ── Generate format reference and exit ────────────────────────────────
    if args.generate_format:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        fmt_path = output_dir / "REPORT_FORMAT.md"
        fmt_path.write_text(generate_report_format(), encoding="utf-8")
        print(f"Report format reference saved to: {fmt_path}")
        return

    if not args.config or not args.data:
        parser.error("--config and --data are required (unless using --generate-format)")

    config = parse_config(args.config)
    data = load_sprint_data(args.data)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sprint_info = data["sprint"]
    sprint_start = date.fromisoformat(sprint_info["start_date"])
    sprint_end = date.fromisoformat(sprint_info["end_date"])
    sprint_goal = sprint_info.get("goal", "")
    report_date = (
        date.fromisoformat(config.report_date)
        if config.report_date
        else date.today()
    )

    issues = data["issues"]
    worklogs = data["worklogs"]

    included_names = [m.name for m in config.team_members if m.included]
    excluded_keys = set(config.excluded_tickets)
    chart_keys = {
        i["key"]
        for i in issues
        if effective_issue_type(i) in ("Story", "Task")
        and i.get("key")
        and i["key"] not in excluded_keys
    }
    chart_worklogs = {k: worklogs.get(k, []) for k in chart_keys}

    work_report = build_sprint_work_report(
        config,
        sprint_start,
        sprint_end,
        issues,
        worklogs,
        report_date=report_date,
    )

    safe_name = config.sprint_name.replace(" ", "_")

    # ── Text report ──────────────────────────────────────────────────────
    if not args.chart_only:
        report_text = generate_text_report(
            config, sprint_start, sprint_end, work_report, sprint_goal=sprint_goal,
        )

        report_path = output_dir / f"sprint_report_{safe_name}.md"
        report_path.write_text(report_text, encoding="utf-8")
        print(f"Text report saved to: {report_path}")

    # ── Burndown chart ───────────────────────────────────────────────────
    if not args.report_only:
        try:
            from burndown_chart import generate_burndown_chart
        except ImportError as e:
            print(
                f"Warning: could not import burndown_chart ({e}). "
                "Install matplotlib: pip install matplotlib",
                file=sys.stderr,
            )
            sys.exit(1)

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
        print(f"Burndown chart saved to: {chart_path}")

    print("Done.")


if __name__ == "__main__":
    main()

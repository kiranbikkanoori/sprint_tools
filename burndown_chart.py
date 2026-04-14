"""
Sprint work-log chart (stacked hours per day by person).

Remaining-work burndown is not shown — see figure subtitle. X-axis uses working
days only (Mon–Fri), matching the previous tool layout.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from utils import worklog_started_date, working_dates_in_range

MEMBER_COLOURS = [
    "#2176FF",  # blue
    "#F77F00",  # orange
    "#06D6A0",  # green
    "#7B2D8E",  # purple
    "#EF476F",  # red-pink
    "#00B4D8",  # cyan
    "#FFD166",  # yellow
    "#073B4C",  # dark teal
]

BAR_ALPHA = 0.85
TODAY_COLOUR = "#FF5722"


def _reset_matplotlib_defaults():
    matplotlib.rcdefaults()
    plt.style.use("default")
    matplotlib.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica", "sans-serif"],
            "font.size": 10,
            "axes.titlesize": 13,
            "axes.labelsize": 12,
            "xtick.labelsize": 9,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
            "savefig.facecolor": "white",
            "axes.grid": True,
            "grid.alpha": 0.3,
        }
    )


def generate_burndown_chart(
    sprint_name: str,
    sprint_start: date,
    sprint_end: date,
    member_names: list[str],
    worklogs: dict[str, list[dict]],
    report_date: date | None = None,
    output_path: str | Path = "sprint_burndown.png",
    *,
    total_planned_hours: float | None = None,
    total_remaining_hours: float | None = None,
) -> Path:
    """
    Save a PNG with stacked daily logged hours (Parent + Standalone worklogs only).

    ``total_planned_hours`` and ``total_remaining_hours`` are accepted for backward
    compatibility with older callers; they are ignored.

    ``worklogs`` should already be restricted to Parent and Standalone issue keys.
    Hours are credited to the worklog author when the author is in ``member_names``.
    """
    _ = (total_planned_hours, total_remaining_hours)
    _reset_matplotlib_defaults()

    report_date = report_date or sprint_end
    log_end = min(sprint_end, report_date)
    output_path = Path(output_path)
    working_days = working_dates_in_range(sprint_start, sprint_end)
    n_days = len(working_days)
    day_indices = list(range(n_days))
    day_labels = [d.strftime("%b %d\n%a") for d in working_days]

    member_daily: dict[str, dict[date, float]] = {m: defaultdict(float) for m in member_names}

    for _key, wl_list in worklogs.items():
        for wl in wl_list:
            wl_date = worklog_started_date(wl)
            if wl_date is None:
                continue
            author = wl["author"]
            if author not in member_names:
                continue
            if not (sprint_start <= wl_date <= log_end):
                continue
            hrs = wl["seconds"] / 3600.0
            member_daily[author][wl_date] += hrs

    today_idx = None
    for i, d in enumerate(working_days):
        if d == report_date or (
            d <= report_date and (i + 1 >= n_days or working_days[i + 1] > report_date)
        ):
            today_idx = i
            break

    fig, ax = plt.subplots(1, 1, figsize=(max(12, n_days * 1.2), 6))
    # Leave enough vertical gap: two-line suptitle, then italic note below (no overlap).
    fig.suptitle(
        f"Sprint work logged: {sprint_name}\n"
        f"({sprint_start.strftime('%b %d')} \u2013 {sprint_end.strftime('%b %d, %Y')})",
        fontsize=15,
        fontweight="bold",
        y=0.99,
    )
    fig.text(
        0.5,
        0.825,
        "Burndown / remaining work: under development (not shown)",
        ha="center",
        fontsize=11,
        style="italic",
        color="#555555",
    )

    bar_day_indices = []
    bar_working_dates = []
    for i, d in enumerate(working_days):
        if d <= log_end:
            bar_day_indices.append(i)
            bar_working_dates.append(d)

    bottom = [0.0] * len(bar_day_indices)
    for idx, member in enumerate(member_names):
        vals = [
            member_daily[member].get(bar_working_dates[j], 0.0) for j in range(len(bar_day_indices))
        ]
        short = member.split()[0]
        colour = MEMBER_COLOURS[idx % len(MEMBER_COLOURS)]
        ax.bar(
            bar_day_indices,
            vals,
            bottom=bottom,
            label=short,
            color=colour,
            alpha=BAR_ALPHA,
            width=0.6,
        )
        bottom = [b + v for b, v in zip(bottom, vals)]

    if today_idx is not None:
        ax.axvline(
            x=today_idx,
            color=TODAY_COLOUR,
            linestyle=":",
            linewidth=1.5,
            alpha=0.6,
            label="Report date",
        )

    ax.set_ylabel("Hours logged (parent + standalone)")
    ax.set_xlabel("Sprint day (working days)")
    ax.legend(loc="upper left", fontsize=9, ncol=min(4, len(member_names) + 1))

    ax.set_xticks(day_indices)
    ax.set_xticklabels(day_labels, rotation=0, ha="center")
    ax.set_xlim(-0.5, n_days - 0.5)
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))

    plt.tight_layout(rect=[0, 0, 1, 0.78])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path))
    plt.close(fig)

    return output_path


if __name__ == "__main__":
    print("This module is meant to be imported. Use sprint_report.py as the CLI entry point.")

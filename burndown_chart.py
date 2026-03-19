"""
Deterministic burndown chart generator.

Produces a two-panel PNG:
  Top:    remaining-work burndown (ideal vs actual)
  Bottom: stacked daily-hours-logged bar chart per person

X-axis uses working days only (weekends excluded), matching how
Jira and other sprint tools display burndown data.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from utils import working_dates_in_range

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

IDEAL_COLOUR = "#888888"
ACTUAL_COLOUR = "#2176FF"
REMAINING_ANNOTATION_COLOUR = "#D32F2F"
FILL_ALPHA = 0.12
BAR_ALPHA = 0.85
TODAY_COLOUR = "#FF5722"


def _reset_matplotlib_defaults():
    """Force a clean matplotlib state so output is machine-independent."""
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
    total_planned_hours: float,
    member_names: list[str],
    worklogs: dict[str, list[dict]],
    report_date: date | None = None,
    total_remaining_hours: float | None = None,
    output_path: str | Path = "sprint_burndown.png",
) -> Path:
    """
    Generate and save a burndown chart PNG.

    X-axis shows working days only (Mon–Fri). Weekends are skipped.
    """
    _reset_matplotlib_defaults()

    report_date = report_date or sprint_end
    output_path = Path(output_path)
    working_days = working_dates_in_range(sprint_start, sprint_end)
    n_days = len(working_days)

    # Use integer indices for X-axis, with date labels
    day_indices = list(range(n_days))
    day_labels = [d.strftime("%b %d\n%a") for d in working_days]

    # ── Aggregate daily hours per member ─────────────────────────────────
    member_daily: dict[str, dict[date, float]] = {m: defaultdict(float) for m in member_names}
    team_daily: dict[date, float] = defaultdict(float)

    for _key, wl_list in worklogs.items():
        for wl in wl_list:
            wl_date = date.fromisoformat(wl["started"][:10])
            author = wl["author"]
            if author not in member_names:
                continue
            if not (sprint_start <= wl_date <= sprint_end):
                continue
            hrs = wl["seconds"] / 3600.0
            member_daily[author][wl_date] += hrs
            team_daily[wl_date] += hrs

    # ── Ideal burndown (linear across working days) ──────────────────────
    daily_burn_rate = total_planned_hours / n_days if n_days else 0
    ideal_y = [total_planned_hours - daily_burn_rate * i for i in range(n_days + 1)]
    ideal_x = list(range(-1, n_days))  # -1 = "Day 0" (start)

    # ── Actual burndown ──────────────────────────────────────────────────
    # Include ALL worklogs (including weekends) so remaining matches Planned vs Logged table.
    # Use Jira's total_remaining_hours for the final point when available (actual state from Jira).
    all_dates = []
    d = sprint_start
    while d <= sprint_end:
        all_dates.append(d)
        d += timedelta(days=1)
    actual_x = [-1]
    actual_y = [total_planned_hours]
    for i, wd in enumerate(working_days):
        if wd > report_date:
            break
        cum_at_wd = sum(team_daily.get(d, 0) for d in all_dates if d <= wd and d <= report_date)
        actual_x.append(i)
        actual_y.append(total_planned_hours - cum_at_wd)

    # Use Jira's total remaining for the final point when available (actual state from Jira)
    if total_remaining_hours is not None and len(actual_y) > 1:
        actual_y[-1] = total_remaining_hours

    # Find "today" index for a vertical marker
    today_idx = None
    for i, d in enumerate(working_days):
        if d == report_date or (d <= report_date and (i + 1 >= n_days or working_days[i + 1] > report_date)):
            today_idx = i
            break

    # ── Create figure ────────────────────────────────────────────────────
    fig, (ax_burn, ax_bar) = plt.subplots(
        2, 1,
        figsize=(max(12, n_days * 1.2), 10),
        gridspec_kw={"height_ratios": [3, 2]},
    )
    fig.suptitle(
        f"Sprint Burndown: {sprint_name}\n"
        f"({sprint_start.strftime('%b %d')} \u2013 {sprint_end.strftime('%b %d, %Y')})",
        fontsize=15,
        fontweight="bold",
        y=0.98,
    )

    # ── Top panel: burndown lines ────────────────────────────────────────
    ax_burn.plot(
        ideal_x, ideal_y, "--",
        color=IDEAL_COLOUR, linewidth=2, label="Ideal Burndown", zorder=3,
    )
    ax_burn.plot(
        actual_x, actual_y, "-o",
        color=ACTUAL_COLOUR, linewidth=2.5, markersize=6,
        label="Actual Remaining", zorder=4,
    )
    ax_burn.fill_between(actual_x, actual_y, alpha=FILL_ALPHA, color=ACTUAL_COLOUR)
    ax_burn.axhline(y=0, color="#4CAF50", linestyle="-", alpha=0.3, linewidth=1)

    if today_idx is not None:
        ax_burn.axvline(x=today_idx, color=TODAY_COLOUR, linestyle=":", linewidth=1.5,
                        alpha=0.6, label="Today")

    final_remaining = actual_y[-1]
    ax_burn.annotate(
        f"{final_remaining:.0f}h remaining",
        xy=(actual_x[-1], final_remaining),
        xytext=(15, 15),
        textcoords="offset points",
        fontsize=10,
        fontweight="bold",
        color=REMAINING_ANNOTATION_COLOUR,
        arrowprops=dict(arrowstyle="->", color=REMAINING_ANNOTATION_COLOUR, lw=1.5),
    )

    ax_burn.set_ylabel("Remaining Work (hours)")
    ax_burn.set_ylim(bottom=-10, top=total_planned_hours * 1.08)
    ax_burn.legend(loc="upper right", fontsize=11)

    ax_burn.set_xticks(day_indices)
    ax_burn.set_xticklabels(day_labels, rotation=0, ha="center")
    ax_burn.set_xlim(-1.5, n_days - 0.5)

    # ── Bottom panel: stacked daily bars ─────────────────────────────────
    bar_day_indices = []
    bar_working_dates = []
    for i, d in enumerate(working_days):
        if d <= report_date:
            bar_day_indices.append(i)
            bar_working_dates.append(d)

    bottom = [0.0] * len(bar_day_indices)

    for idx, member in enumerate(member_names):
        vals = [member_daily[member].get(bar_working_dates[j], 0) for j in range(len(bar_day_indices))]
        short = member.split()[0]
        colour = MEMBER_COLOURS[idx % len(MEMBER_COLOURS)]
        ax_bar.bar(
            bar_day_indices, vals, bottom=bottom,
            label=short, color=colour, alpha=BAR_ALPHA, width=0.6,
        )
        bottom = [b + v for b, v in zip(bottom, vals)]

    ideal_daily = daily_burn_rate
    ax_bar.axhline(
        y=ideal_daily, color=IDEAL_COLOUR, linestyle="--", linewidth=1.5,
        label=f"Ideal rate ({ideal_daily:.0f}h/day)",
    )

    if today_idx is not None:
        ax_bar.axvline(x=today_idx, color=TODAY_COLOUR, linestyle=":", linewidth=1.5, alpha=0.6)

    ax_bar.set_ylabel("Hours Logged")
    ax_bar.set_xlabel("Sprint Day")
    ax_bar.legend(loc="upper left", fontsize=9, ncol=min(4, len(member_names) + 1))

    ax_bar.set_xticks(day_indices)
    ax_bar.set_xticklabels(day_labels, rotation=0, ha="center")
    ax_bar.set_xlim(-0.5, n_days - 0.5)
    ax_bar.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path))
    plt.close(fig)

    return output_path


if __name__ == "__main__":
    print("This module is meant to be imported. Use sprint_report.py as the CLI entry point.")

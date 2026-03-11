#!/usr/bin/env python3
"""
PR Cycle Time Report
====================
Calculates LinearB-style cycle time metrics for PRs linked to Jira sprint tickets.

Metrics per PR:
  - Coding Time:  First commit on branch → PR creation
  - Pickup Time:  PR creation → First human review
  - Review Time:  First human review → PR merge
  - Cycle Time:   First commit → PR merge (end-to-end)

Usage:
    python cycle_time_report.py \\
        --data sprint_data_Wi-Fi_LMAC_2026_5.json \\
        --config sprint_report_config.md \\
        --repo SiliconLabsInternal/wifi-nwp-firmware

    python cycle_time_report.py \\
        --data sprint_data.json --config config.md \\
        --repo OWNER/REPO --output-dir ./output
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_parser import parse_config

BOT_LOGINS = {
    "siliconlabs-read-all-repos[bot]",
    "silabs-sonarqube-server[bot]",
    "dependabot[bot]",
    "github-actions[bot]",
    "codecov[bot]",
}


def business_hours_between(start: datetime, end: datetime) -> float:
    """Clock hours between two datetimes with Saturday/Sunday hours removed."""
    if not start or not end or start >= end:
        return 0.0

    total_hours = 0.0
    current = start
    one_day = timedelta(days=1)

    while current < end:
        next_midnight = (current + one_day).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        day_end = min(end, next_midnight)

        if current.weekday() < 5:  # Mon–Fri only
            total_hours += (day_end - current).total_seconds() / 3600

        current = next_midnight

    return total_hours


@dataclass
class PRMetrics:
    pr_number: int
    title: str
    url: str
    author: str
    state: str
    jira_key: str
    assignee: str
    created_at: datetime | None = None
    merged_at: datetime | None = None
    first_commit_at: datetime | None = None
    first_human_review_at: datetime | None = None
    total_commits: int = 0
    total_human_reviews: int = 0
    review_rounds: int = 0
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0

    @property
    def coding_time_hours(self) -> float | None:
        if self.first_commit_at and self.created_at:
            return business_hours_between(self.first_commit_at, self.created_at)
        return None

    @property
    def pickup_time_hours(self) -> float | None:
        if self.created_at and self.first_human_review_at:
            return business_hours_between(self.created_at, self.first_human_review_at)
        if self.created_at and not self.first_human_review_at:
            return business_hours_between(self.created_at, datetime.now(timezone.utc))
        return None

    @property
    def review_time_hours(self) -> float | None:
        if self.first_human_review_at and self.merged_at:
            return business_hours_between(self.first_human_review_at, self.merged_at)
        return None

    @property
    def cycle_time_hours(self) -> float | None:
        if self.first_commit_at and self.merged_at:
            return business_hours_between(self.first_commit_at, self.merged_at)
        return None


# ── GitHub CLI helpers ───────────────────────────────────────────────────────

def run_gh(args: list[str], timeout: int = 30) -> str:
    cmd = ["gh"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return ""
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def parse_iso(dt_str: str) -> datetime | None:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def find_prs_for_ticket(repo: str, ticket_key: str) -> list[dict]:
    output = run_gh([
        "pr", "list", "--repo", repo,
        "--search", ticket_key,
        "--state", "all",
        "--json", "number,title,author,createdAt,mergedAt,state,headRefName,additions,deletions,changedFiles,url",
        "--limit", "10",
    ])
    if not output:
        return []
    try:
        prs = json.loads(output)
        return [
            pr for pr in prs
            if ticket_key.lower() in pr.get("headRefName", "").lower()
            or ticket_key.lower() in pr.get("title", "").lower()
        ]
    except json.JSONDecodeError:
        return []


def get_pr_commits(repo: str, pr_number: int) -> list[dict]:
    output = run_gh(["api", f"repos/{repo}/pulls/{pr_number}/commits", "--paginate"], timeout=30)
    if not output:
        return []
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return []


def get_pr_reviews(repo: str, pr_number: int) -> list[dict]:
    output = run_gh(["api", f"repos/{repo}/pulls/{pr_number}/reviews"], timeout=30)
    if not output:
        return []
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return []


def analyze_pr(repo: str, pr_data: dict, ticket_key: str, assignee: str) -> PRMetrics:
    pr_num = pr_data["number"]
    metrics = PRMetrics(
        pr_number=pr_num,
        title=pr_data.get("title", ""),
        url=pr_data.get("url", f"https://github.com/{repo}/pull/{pr_num}"),
        author=pr_data.get("author", {}).get("login", "unknown"),
        state=pr_data.get("state", ""),
        jira_key=ticket_key,
        assignee=assignee,
        created_at=parse_iso(pr_data.get("createdAt", "")),
        merged_at=parse_iso(pr_data.get("mergedAt", "")),
        additions=pr_data.get("additions", 0),
        deletions=pr_data.get("deletions", 0),
        changed_files=pr_data.get("changedFiles", 0),
    )

    commits = get_pr_commits(repo, pr_num)
    metrics.total_commits = len(commits)
    commit_dates = []
    for c in commits:
        dt = parse_iso(c.get("commit", {}).get("author", {}).get("date", ""))
        if dt:
            commit_dates.append(dt)
    if commit_dates:
        metrics.first_commit_at = min(commit_dates)

    reviews = get_pr_reviews(repo, pr_num)
    human_reviews = [
        r for r in reviews
        if r.get("user", {}).get("login", "") not in BOT_LOGINS
        and r.get("state") != "PENDING"
    ]
    metrics.total_human_reviews = len(human_reviews)
    metrics.review_rounds = len([
        r for r in human_reviews
        if r.get("state") in ("CHANGES_REQUESTED", "APPROVED")
    ])

    review_dates = []
    for r in human_reviews:
        dt = parse_iso(r.get("submitted_at", ""))
        if dt:
            review_dates.append(dt)
    if review_dates:
        metrics.first_human_review_at = min(review_dates)

    return metrics


# ── Formatting helpers ───────────────────────────────────────────────────────

def fmt(hours: float | None) -> str:
    if hours is None:
        return "N/A"
    if hours < 1:
        return f"{hours * 60:.0f}m"
    if hours < 24:
        return f"{hours:.1f}h"
    days = hours / 24
    if days < 7:
        return f"{days:.1f}d"
    return f"{days / 7:.1f}w"


def fmt_detail(hours: float | None) -> str:
    if hours is None:
        return "N/A"
    if hours < 1:
        return f"{hours * 60:.0f} min"
    if hours < 24:
        return f"{hours:.1f} hours"
    days = hours / 24
    return f"{days:.1f} days ({hours:.0f}h)"


def avg(values: list[float]) -> float | None:
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else None


# ── Report generation ────────────────────────────────────────────────────────

def generate_report(
    all_metrics: list[PRMetrics],
    team_members: list,
    sprint_name: str,
    repo: str,
    tickets_without_pr: list[dict],
) -> str:
    lines: list[str] = []
    lines.append(f"# PR Cycle Time Report — {sprint_name}")
    lines.append("")
    lines.append(f"**Repo:** `{repo}`  ")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ")
    lines.append(f"**Total PRs analyzed:** {len(all_metrics)}  ")
    lines.append(f"**Tickets without PRs:** {len(tickets_without_pr)}")
    lines.append("")

    by_person: dict[str, list[PRMetrics]] = defaultdict(list)
    for m in all_metrics:
        by_person[m.assignee].append(m)

    # ── Summary Table ────────────────────────────────────────────────────
    lines.append("## Summary by Team Member")
    lines.append("")
    lines.append("| Person | PRs | Avg Coding | Avg Pickup | Avg Review | Avg Cycle |")
    lines.append("|--------|:---:|:----------:|:----------:|:----------:|:---------:|")

    team_coding: list[float] = []
    team_pickup: list[float] = []
    team_review: list[float] = []
    team_cycle: list[float] = []

    for person in sorted(by_person.keys()):
        prs = by_person[person]
        c = [p.coding_time_hours for p in prs if p.coding_time_hours is not None]
        p_ = [p.pickup_time_hours for p in prs if p.pickup_time_hours is not None]
        r = [p.review_time_hours for p in prs if p.review_time_hours is not None]
        cy = [p.cycle_time_hours for p in prs if p.cycle_time_hours is not None]
        team_coding.extend(c)
        team_pickup.extend(p_)
        team_review.extend(r)
        team_cycle.extend(cy)
        lines.append(
            f"| {person} | {len(prs)} | {fmt(avg(c))} | {fmt(avg(p_))} | "
            f"{fmt(avg(r))} | {fmt(avg(cy))} |"
        )

    lines.append(
        f"| **TEAM AVERAGE** | **{len(all_metrics)}** | **{fmt(avg(team_coding))}** | "
        f"**{fmt(avg(team_pickup))}** | **{fmt(avg(team_review))}** | "
        f"**{fmt(avg(team_cycle))}** |"
    )
    lines.append("")

    # ── Metric Legend ────────────────────────────────────────────────────
    lines.append("> **Coding Time** = First commit → PR creation | "
                 "**Pickup Time** = PR creation → First human review | "
                 "**Review Time** = First human review → PR merge | "
                 "**Cycle Time** = First commit → PR merge  ")
    lines.append("> *All times exclude weekends (Sat/Sun).*")
    lines.append("")

    # ── Per-person Detail ────────────────────────────────────────────────
    lines.append("---")
    lines.append("")
    lines.append("## Detailed Breakdown by Person")
    lines.append("")

    for person in sorted(by_person.keys()):
        prs = by_person[person]
        lines.append(f"### {person}")
        lines.append("")

        if not prs:
            lines.append("_No PRs found._")
            lines.append("")
            continue

        lines.append("| PR | Jira | State | Coding | Pickup | Review | Cycle | Size | Commits | Reviews |")
        lines.append("|:---|:-----|:-----:|:------:|:------:|:------:|:-----:|:----:|:-------:|:-------:|")

        for p in sorted(prs, key=lambda x: x.created_at or datetime.min.replace(tzinfo=timezone.utc)):
            state = p.state.lower()
            lines.append(
                f"| [#{p.pr_number}]({p.url}) | {p.jira_key} | {state} | "
                f"{fmt(p.coding_time_hours)} | {fmt(p.pickup_time_hours)} | "
                f"{fmt(p.review_time_hours)} | {fmt(p.cycle_time_hours)} | "
                f"+{p.additions}/-{p.deletions} | {p.total_commits} | "
                f"{p.total_human_reviews} |"
            )

        lines.append("")
        c = [p.coding_time_hours for p in prs if p.coding_time_hours is not None]
        p_ = [p.pickup_time_hours for p in prs if p.pickup_time_hours is not None]
        r = [p.review_time_hours for p in prs if p.review_time_hours is not None]
        cy = [p.cycle_time_hours for p in prs if p.cycle_time_hours is not None]
        lines.append(
            f"> **{person} avg:** Coding {fmt_detail(avg(c))} | "
            f"Pickup {fmt_detail(avg(p_))} | Review {fmt_detail(avg(r))} | "
            f"Cycle {fmt_detail(avg(cy))}"
        )
        lines.append("")

    # ── Insights ─────────────────────────────────────────────────────────
    lines.append("---")
    lines.append("")
    lines.append("## Team Insights")
    lines.append("")

    merged_prs = [p for p in all_metrics if p.cycle_time_hours is not None]
    if merged_prs:
        fastest = min(merged_prs, key=lambda p: p.cycle_time_hours)
        slowest = max(merged_prs, key=lambda p: p.cycle_time_hours)
        lines.append(
            f"- **Fastest merge:** [#{fastest.pr_number}]({fastest.url}) "
            f"({fastest.jira_key}) — {fmt_detail(fastest.cycle_time_hours)}"
        )
        lines.append(
            f"- **Slowest merge:** [#{slowest.pr_number}]({slowest.url}) "
            f"({slowest.jira_key}) — {fmt_detail(slowest.cycle_time_hours)}"
        )

    if team_coding and team_pickup and team_review:
        vals = [("Coding", avg(team_coding)), ("Pickup", avg(team_pickup)), ("Review", avg(team_review))]
        vals = [(n, v) for n, v in vals if v is not None]
        if vals:
            bottleneck = max(vals, key=lambda x: x[1])
            lines.append(f"- **Biggest bottleneck:** {bottleneck[0]} Time ({fmt_detail(bottleneck[1])} avg)")

    open_prs = [p for p in all_metrics if p.state == "OPEN"]
    if open_prs:
        lines.append(f"- **Open PRs awaiting review/merge:** {len(open_prs)}")
        for p in open_prs:
            age = ""
            if p.created_at:
                age_h = (datetime.now(timezone.utc) - p.created_at).total_seconds() / 3600
                age = f" — open for {fmt_detail(age_h)}"
            reviewed = "reviewed" if p.first_human_review_at else "**no review yet**"
            lines.append(f"  - [#{p.pr_number}]({p.url}) ({p.jira_key}){age}, {reviewed}")

    lines.append("")

    # ── Tickets without PRs ──────────────────────────────────────────────
    if tickets_without_pr:
        lines.append("---")
        lines.append("")
        lines.append("## Tickets Without PRs")
        lines.append("")
        lines.append("| Ticket | Assignee | Status | Summary |")
        lines.append("|:-------|:---------|:------:|:--------|")
        for t in tickets_without_pr:
            lines.append(
                f"| {t['key']} | {t.get('assignee', 'Unassigned')} | "
                f"{t.get('status', '?')} | {t.get('summary', '')[:70]} |"
            )
        lines.append("")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate PR cycle time report for sprint tickets.")
    parser.add_argument("--data", "-d", required=True, help="Sprint data JSON (from fetch_via_mcp.py)")
    parser.add_argument("--config", "-c", required=True, help="Sprint report config markdown")
    parser.add_argument("--repo", "-r", required=True, help="GitHub repo (OWNER/REPO)")
    parser.add_argument("--output-dir", "-o", default="./output", help="Output directory")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"Error: data file not found: {data_path}", file=sys.stderr)
        sys.exit(1)

    with open(data_path) as f:
        sprint_data = json.load(f)

    config = parse_config(args.config)
    sprint_name = sprint_data.get("sprint", {}).get("name", config.sprint_name)
    issues = sprint_data.get("issues", [])
    repo = args.repo

    tickets = [i for i in issues if i.get("type") != "Parent"]

    print(f"Sprint:  {sprint_name}")
    print(f"Repo:    {repo}")
    print(f"Tickets: {len(tickets)} (excluding parent stories)")
    print()

    auth_out = run_gh(["auth", "token"], timeout=10)
    if not auth_out.strip():
        print("Error: gh CLI not authenticated. Run: gh auth login", file=sys.stderr)
        sys.exit(1)

    all_metrics: list[PRMetrics] = []
    tickets_without_pr: list[dict] = []
    seen_prs: set[int] = set()

    for idx, ticket in enumerate(tickets):
        key = ticket["key"]
        assignee = ticket.get("assignee", "Unassigned")
        print(f"  [{idx + 1}/{len(tickets)}] {key:15s} ({assignee:25s}) ", end="", flush=True)

        prs = find_prs_for_ticket(repo, key)

        if not prs:
            print("— no PR")
            tickets_without_pr.append(ticket)
            continue

        for pr_data in prs:
            pr_num = pr_data["number"]
            if pr_num in seen_prs:
                print(f"— PR #{pr_num} (dup, skipped)")
                continue
            seen_prs.add(pr_num)
            print(f"→ PR #{pr_num} ", end="", flush=True)
            metrics = analyze_pr(repo, pr_data, key, assignee)
            all_metrics.append(metrics)
            print(f"[coding={fmt(metrics.coding_time_hours)} pickup={fmt(metrics.pickup_time_hours)} "
                  f"review={fmt(metrics.review_time_hours)}]")

    print()
    print(f"PRs analyzed:       {len(all_metrics)}")
    print(f"Tickets without PR: {len(tickets_without_pr)}")
    print()

    report = generate_report(all_metrics, config.team_members, sprint_name, repo, tickets_without_pr)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe = sprint_name.replace(" ", "_")

    md_path = output_dir / f"cycle_time_report_{safe}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report)

    json_out: list[dict] = []
    for m in all_metrics:
        json_out.append({
            "pr_number": m.pr_number,
            "title": m.title,
            "url": m.url,
            "author": m.author,
            "state": m.state,
            "jira_key": m.jira_key,
            "assignee": m.assignee,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "merged_at": m.merged_at.isoformat() if m.merged_at else None,
            "first_commit_at": m.first_commit_at.isoformat() if m.first_commit_at else None,
            "first_human_review_at": m.first_human_review_at.isoformat() if m.first_human_review_at else None,
            "coding_time_hours": m.coding_time_hours,
            "pickup_time_hours": m.pickup_time_hours,
            "review_time_hours": m.review_time_hours,
            "cycle_time_hours": m.cycle_time_hours,
            "total_commits": m.total_commits,
            "total_human_reviews": m.total_human_reviews,
            "review_rounds": m.review_rounds,
            "additions": m.additions,
            "deletions": m.deletions,
            "changed_files": m.changed_files,
        })

    json_path = output_dir / f"cycle_time_data_{safe}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_out, f, indent=2, ensure_ascii=False)

    print(f"Report:   {md_path}")
    print(f"Raw data: {json_path}")

    # Terminal summary
    print()
    print("=" * 65)
    print("  CYCLE TIME SUMMARY")
    print("=" * 65)

    by_person: dict[str, list[PRMetrics]] = defaultdict(list)
    for m in all_metrics:
        by_person[m.assignee].append(m)

    for person in sorted(by_person.keys()):
        prs = by_person[person]
        c = [p.coding_time_hours for p in prs if p.coding_time_hours is not None]
        p_ = [p.pickup_time_hours for p in prs if p.pickup_time_hours is not None]
        r = [p.review_time_hours for p in prs if p.review_time_hours is not None]
        cy = [p.cycle_time_hours for p in prs if p.cycle_time_hours is not None]
        print(f"\n  {person} ({len(prs)} PRs)")
        print(f"    Coding:  {fmt_detail(avg(c)):>20s}")
        print(f"    Pickup:  {fmt_detail(avg(p_)):>20s}")
        print(f"    Review:  {fmt_detail(avg(r)):>20s}")
        print(f"    Cycle:   {fmt_detail(avg(cy)):>20s}")

    all_c = [p.coding_time_hours for p in all_metrics if p.coding_time_hours is not None]
    all_p = [p.pickup_time_hours for p in all_metrics if p.pickup_time_hours is not None]
    all_r = [p.review_time_hours for p in all_metrics if p.review_time_hours is not None]
    all_cy = [p.cycle_time_hours for p in all_metrics if p.cycle_time_hours is not None]

    print(f"\n  {'─' * 45}")
    print(f"  TEAM AVERAGE ({len(all_metrics)} PRs)")
    print(f"    Coding:  {fmt_detail(avg(all_c)):>20s}")
    print(f"    Pickup:  {fmt_detail(avg(all_p)):>20s}")
    print(f"    Review:  {fmt_detail(avg(all_r)):>20s}")
    print(f"    Cycle:   {fmt_detail(avg(all_cy)):>20s}")
    print()


if __name__ == "__main__":
    main()

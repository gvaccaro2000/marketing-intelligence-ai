"""Build the Dice Kingdom budget simulator page from the weekly UA outputs.

Fills the DATA and PRESET blocks (and the baseline window label) of the template
artifacts/budget_simulator.html and writes reports/budget_simulator.html:

  DATA    baseline per channel and per country = average of the last 4 complete weeks in
          reports/dashboard/weekly_{total,channel,country}.csv (scripts/export_dashboard_data.py):
          weekly spend, weekly installs, D7 ROAS = sum D7 revenue / sum D7-mature spend.
  PRESET  the recommended action's `preset` from reports/weekly_ua_<week>.json
          (scripts/weekly_ua_report.py): {mode, moves: {line: USD/wk}, rebalance}. A report that
          holds budgets (failed checks, no candidate) gives an empty preset and a disabled button.

Checks before writing: the window is N consecutive complete weeks, every line has a row in each
week, channel and country lines sum to the weekly totals over the window, the report is for the
latest exported week, and every preset line exists in the baseline.

Usage:
  python scripts/build_simulator.py [--report reports/weekly_ua_<week>.json] [--weeks 4]

Exit codes: 0 ok, 1 validation failed (nothing written), 2 missing input.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DASH = ROOT / "reports" / "dashboard"
DEFAULT_TEMPLATE = ROOT / "artifacts" / "budget_simulator.html"
DEFAULT_OUT = ROOT / "reports" / "budget_simulator.html"
MONEY_TOL = 0.01  # reconciliation tolerance in USD
SUMMED = ["spend", "installs", "d7_revenue", "d7_mature_spend"]


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as f:
        return [{k: (v if k in ("week_start", "channel", "country") else float(v or 0))
                 for k, v in r.items()} for r in csv.DictReader(f)]


def ratio(n, d):
    return None if not d else n / d


def money(x: float) -> str:
    return f"${abs(x):,.0f}"


def window_label(first: date, last_sunday: date) -> str:
    return f"{first:%b} {first.day} – {last_sunday:%b} {last_sunday.day}, {last_sunday.year}"


def baseline(rows: list[dict], dim: str, weeks: list[str], checks: list) -> list[dict]:
    """Average week per line over `weeks`, ordered by baseline spend (largest first)."""
    keys = sorted({r[dim] for r in rows if r["week_start"] in weeks})
    out = []
    missing = []
    for k in keys:
        rs = [r for r in rows if r[dim] == k and r["week_start"] in weeks]
        if len(rs) != len(weeks):
            missing.append(f"{k} ({len(rs)}/{len(weeks)} weeks)")
        t = {m: sum(r[m] for r in rs) for m in SUMMED}
        out.append({"name": k, **t,
                    "roas": ratio(t["d7_revenue"], t["d7_mature_spend"])})
    checks.append((f"every {dim} has all {len(weeks)} weeks", not missing,
                   ", ".join(missing) or f"{len(keys)} lines"))
    nulls = [b["name"] for b in out if b["roas"] is None]
    checks.append((f"{dim} D7 ROAS defined (D7-mature spend > 0)", not nulls,
                   ", ".join(nulls) or "ok"))
    return sorted(out, key=lambda b: b["spend"], reverse=True)


def js_json(obj) -> str:
    # compact JSON that can't close the <script> element it is embedded in
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def replace_block(page: str, name: str, body: str) -> str:
    pat = re.compile(rf"(/\*BEGIN:{name}\*/\n).*?(\n\s*/\*END:{name}\*/)", re.S)
    if len(pat.findall(page)) != 1:
        raise ValueError(f"template must contain exactly one {name} block")
    return pat.sub(lambda m: m.group(1) + body + m.group(2), page)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dashboard-dir", default=str(DEFAULT_DASH))
    ap.add_argument("--report", help="weekly report JSON (default: reports/weekly_ua_<latest week>.json)")
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--weeks", type=int, default=4, help="complete weeks in the baseline (default 4)")
    args = ap.parse_args()

    dash = Path(args.dashboard_dir)
    try:
        total = read_csv(dash / "weekly_total.csv")
        chan = read_csv(dash / "weekly_channel.csv")
        ctry = read_csv(dash / "weekly_country.csv")
    except FileNotFoundError as e:
        print(f"error: {e.filename} missing; run scripts/export_dashboard_data.py first", file=sys.stderr)
        return 2

    all_weeks = sorted(r["week_start"] for r in total)
    weeks = all_weeks[-args.weeks:]
    latest = weeks[-1] if weeks else None
    report_path = Path(args.report) if args.report else ROOT / "reports" / f"weekly_ua_{latest}.json"
    if not report_path.exists():
        print(f"error: {report_path} missing; run scripts/weekly_ua_report.py first", file=sys.stderr)
        return 2
    report = json.loads(report_path.read_text())

    checks = []
    consecutive = all(date.fromisoformat(b) - date.fromisoformat(a) == timedelta(days=7)
                      for a, b in zip(weeks, weeks[1:]))
    checks.append((f"{args.weeks} consecutive complete weeks", len(weeks) == args.weeks and consecutive,
                   f"{weeks[0] if weeks else '-'} → {latest or '-'} ({len(weeks)} weeks)"))

    data = {"channel": baseline(chan, "channel", weeks, checks),
            "country": baseline(ctry, "country", weeks, checks)}
    tot = {m: sum(r[m] for r in total if r["week_start"] in weeks) for m in SUMMED}
    for dim, rows in data.items():
        off = [f"{m} {sum(b[m] for b in rows):.2f} vs {tot[m]:.2f}" for m in SUMMED
               if abs(sum(b[m] for b in rows) - tot[m]) > MONEY_TOL]
        checks.append((f"{dim} lines sum to weekly totals over the window", not off,
                       "; ".join(off) or ", ".join(SUMMED)))

    checks.append(("report is for the latest exported week", report.get("week_start") == latest,
                   f"report {report.get('week_start')} vs export {latest} "
                   "(run weekly_ua_report.py without --week)"))
    if "preset" not in report:
        checks.append(("report has a preset", False, "re-run scripts/weekly_ua_report.py"))
    preset = report.get("preset")
    if preset:
        names = {b["name"] for b in data.get(preset["mode"], [])}
        unknown = [k for k in preset["moves"] if k not in names]
        checks.append(("preset lines exist in the baseline", not unknown,
                       f"{preset['mode']}: " + (", ".join(unknown) or ", ".join(preset["moves"]))))

    failed = [c for c in checks if not c[1]]
    print(f"validation: {len(checks) - len(failed)}/{len(checks)} passed")
    for n, ok, d in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print("not writing the simulator: validation failed", file=sys.stderr)
        return 1

    n = len(weeks)
    first, last_sunday = date.fromisoformat(weeks[0]), date.fromisoformat(latest) + timedelta(days=6)
    win = window_label(first, last_sunday)
    js_data = {dim: [{"name": b["name"], "spend": round(b["spend"] / n), "installs": round(b["installs"] / n),
                      "roas": round(b["roas"], 4)} for b in rows] for dim, rows in data.items()}
    if preset:
        label = ", ".join(f"{k} {'+' if v > 0 else '−'}{money(v)}/wk" for k, v in preset["moves"].items())
        if preset["rebalance"]:
            label += ", freed budget spread over the other lines"
        js_preset = {"mode": preset["mode"], "moves": {k: round(v) for k, v in preset["moves"].items()},
                     "rebalance": bool(preset["rebalance"]), "label": label}
        note = preset["text"]
    else:
        js_preset = {"mode": "channel", "moves": {}, "rebalance": False,
                     "label": "No budget change recommended this week"}
        note = "hold budgets (no preset)."
    note = note.replace("*/", "* /").replace("\n", " ")

    data_block = (
        f"  // Baseline: average complete week {win}, from scripts/export_dashboard_data.py "
        f"(weekly_channel.csv / weekly_country.csv).\n"
        f"  // D7 ROAS = D7 revenue / D7-mature spend over those {n} weeks. Generated by scripts/build_simulator.py.\n"
        f"  const DATA = {js_json(js_data)};")
    preset_block = (
        f"  // Recommendation from the weekly UA report (week of {latest}): {note}\n"
        f"  // moves = USD/wk per line; rebalance = spread the freed budget over the untouched lines afterwards.\n"
        f"  const PRESET = {js_json(js_preset)};")

    page = Path(args.template).read_text()
    try:
        page = replace_block(page, "DATA", data_block)
        page = replace_block(page, "PRESET", preset_block)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    page, k = re.subn(r'(<span id="win">).*?(</span>)', lambda m: m.group(1) + html.escape(win) + m.group(2), page)
    if k != 1:
        print('error: template must contain exactly one <span id="win">', file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(f"baseline: average of {n} complete weeks, {win} (D7 ROAS on D7-mature cohorts)")
    print(f"preset: {js_preset['label']} ({js_preset['mode']}{', rebalanced' if js_preset['rebalance'] else ''})")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

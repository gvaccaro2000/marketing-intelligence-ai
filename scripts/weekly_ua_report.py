"""Weekly UA report for Dice Kingdom.

Runs the vetted SQL in sql/weekly_ua/ against data/marketing.duckdb, validates the numbers,
computes week-over-week (WoW) changes per channel and per country, and writes:

  reports/weekly_ua_<week_start>.md      full report (validation log, channel + country tables)
  reports/weekly_ua_<week_start>.slack   Slack mrkdwn summary (headline, 3 drivers, 1 action, table)
  reports/weekly_ua_<week_start>.json    all computed metrics, for review

Weeks run Monday-Sunday. Default: the last complete week on or before the data as-of date.

Usage:
  python scripts/weekly_ua_report.py                    # last complete week
  python scripts/weekly_ua_report.py --week 2026-08-12  # week containing that date
  python scripts/weekly_ua_report.py --post             # also post to Slack

Exit codes: 0 ok, 1 validation failed (report written, Slack post blocked), 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql" / "weekly_ua"
DEFAULT_DB = ROOT / "data" / "marketing.duckdb"
DEFAULT_OUT = ROOT / "reports"

CHANNEL_ORDER = ["Meta", "Google", "AppLovin", "TikTok", "Unity"]
COUNTRY_ORDER = ["US", "UK", "DE", "FR", "JP", "BR"]

# Action thresholds (relative to blended paid D7 ROAS for the week).
TRIM_BELOW = 0.90   # channel D7 ROAS < 90% of blended -> trim candidate
SCALE_ABOVE = 1.05  # channel D7 ROAS > 105% of blended, not falling, CPI not up >5% -> scale
SHIFT_SHARE = 0.10  # suggested budget shift: 10% of the trimmed channel's weekly spend
MONEY_TOL = 0.01    # reconciliation tolerance in USD


# --------------------------------------------------------------------------------------
# Data access
# --------------------------------------------------------------------------------------

def run_sql(con: duckdb.DuckDBPyConnection, name: str, params: dict) -> list[dict]:
    sql = (SQL_DIR / name).read_text()
    used = {k: v for k, v in params.items() if f"${k}" in sql}
    cur = con.execute(sql, used)
    cols = [d[0] for d in cur.description]
    rows = []
    for r in cur.fetchall():
        row = {}
        for c, v in zip(cols, r):
            if isinstance(v, Decimal):
                v = float(v)
            elif isinstance(v, date):
                v = v.isoformat()
            row[c] = v
        rows.append(row)
    return rows


def resolve_week(con, requested: str | None) -> tuple[date, date, date]:
    """Return (week_start, as_of, data_min). week_start is a Monday."""
    data_min, as_of = con.execute("SELECT MIN(date), MAX(date) FROM ua_spend").fetchone()
    if requested:
        d = date.fromisoformat(requested)
        week_start = d - timedelta(days=d.weekday())
    else:
        # last Sunday on or before as_of, then back to its Monday
        last_sunday = as_of - timedelta(days=(as_of.weekday() + 1) % 7)
        week_start = last_sunday - timedelta(days=6)
    week_end = week_start + timedelta(days=6)
    if week_end > as_of:
        raise ValueError(f"week {week_start}..{week_end} is not complete (data as-of {as_of})")
    if week_start - timedelta(days=7) < data_min:
        raise ValueError(f"no complete previous week before {week_start} (data starts {data_min})")
    return week_start, as_of, data_min


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------

def close(a, b, tol=MONEY_TOL) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def validate(delivery, quality, reconcile, nulls, outliers, organic, kpis) -> tuple[list, list]:
    """Return (checks, warnings). checks = [(name, passed, detail)]."""
    checks: list[tuple[str, bool, str]] = []

    # 1. ua_spend -> cohort grain vs cohorts, row for row
    for r in reconcile:
        p = r["period"]
        ok = (r["rows_only_in_cohorts"] == 0 and r["rows_only_in_ua_spend"] == 0
              and r["rows_install_mismatch"] == 0 and r["ua_installs"] == r["cohort_installs"])
        checks.append((f"[{p}] installs ua_spend vs cohorts", ok,
                       f"{r['grain_rows']} grain rows, {r['rows_install_mismatch']} mismatched, "
                       f"{r['rows_only_in_cohorts']}/{r['rows_only_in_ua_spend']} orphan; "
                       f"{r['ua_installs']:,.0f} vs {r['cohort_installs']:,.0f}"))
        ok = close(r["ua_paid_spend"], r["joined_paid_spend"]) and r["organic_spend"] == 0
        checks.append((f"[{p}] paid spend survives cohort join", ok,
                       f"${r['ua_paid_spend']:,.2f} vs ${r['joined_paid_spend']:,.2f}; "
                       f"organic spend ${r['organic_spend']:,.2f}"))

    rec = {r["period"]: r for r in reconcile}
    org = {r["period"]: r["installs"] for r in organic}
    for p in ("cur", "prev"):
        # 2. breakdown rows sum to totals (no fan-out, nothing dropped)
        for name, rows, cols in (("delivery", delivery, ("spend", "installs", "impressions", "clicks")),
                                 ("cohort quality", quality, ("spend", "installs"))):
            tot = next(r for r in rows if r["dim"] == "total" and r["period"] == p)
            for dim in ("channel", "country"):
                parts = [r for r in rows if r["dim"] == dim and r["period"] == p]
                bad = [c for c in cols if not close(sum(x[c] for x in parts), tot[c])]
                checks.append((f"[{p}] {name}: {dim} rows sum to total", not bad,
                               "ok" if not bad else f"mismatch in {', '.join(bad)}"))
        # 3. the two paid sources agree with each other and with the reconciliation
        d_tot = next(r for r in delivery if r["dim"] == "total" and r["period"] == p)
        q_tot = next(r for r in quality if r["dim"] == "total" and r["period"] == p)
        ok = (close(d_tot["spend"], q_tot["spend"]) and close(d_tot["spend"], rec[p]["ua_paid_spend"])
              and d_tot["installs"] == q_tot["installs"]
              and d_tot["installs"] + org[p] == rec[p]["cohort_installs"])
        checks.append((f"[{p}] delivery vs cohort totals (spend, paid+organic installs)", ok,
                       f"spend ${d_tot['spend']:,.2f} / ${q_tot['spend']:,.2f}; installs "
                       f"{d_tot['installs']:,.0f} paid + {org[p]:,.0f} organic = "
                       f"{d_tot['installs'] + org[p]:,.0f} vs cohorts {rec[p]['cohort_installs']:,.0f}"))
        k = next(r for r in kpis if r["period"] == p)
        checks.append((f"[{p}] daily_kpis has 7 days", k["days"] == 7, f"{k['days']} days"))

    # 4. NULL / impossible-value checks
    for r in nulls:
        checks.append((r["check_name"], r["failures"] == 0, f"{r['failures']} failing rows"))

    # 5. outliers are warnings, not failures
    warnings = []
    for o in outliers:
        who = o["channel"] if o["country"] == "all" else f"{o['channel']} {o['country']}"
        val = f"${o['value']:,.2f}" if o["metric"] in ("spend", "cpi") else f"{o['value']:,.0f}"
        base = (f"${o['baseline_median']:,.2f}" if o["metric"] in ("spend", "cpi")
                else f"{o['baseline_median']:,.0f}")
        warnings.append({**o, "label": f"{who} {o['metric']} on {o['date']}: {val} vs 28d median {base} "
                                        f"(robust z {o['robust_z']:+.1f})"})
    return checks, warnings


# --------------------------------------------------------------------------------------
# WoW
# --------------------------------------------------------------------------------------

def pct(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return cur / prev - 1


def wow_table(delivery, quality) -> dict:
    """{(dim, key): {metric_cur, metric_prev, metric_pct / metric_pp}}"""
    out: dict = {}
    for rows, metrics in ((delivery, ("spend", "installs", "cpi", "ctr", "ipm")),
                          (quality, ("d1_retention", "d7_retention", "payer_conversion_d7",
                                     "roas_d7", "spend_d7_mature", "d7_max_install_date"))):
        for r in rows:
            e = out.setdefault((r["dim"], r["key"]), {"dim": r["dim"], "key": r["key"]})
            for m in metrics:
                e[f"{m}_{r['period']}"] = r[m]
    for e in out.values():
        for m in ("spend", "installs", "cpi", "ctr", "ipm"):
            e[f"{m}_pct"] = pct(e.get(f"{m}_cur"), e.get(f"{m}_prev"))
        for m in ("d1_retention", "d7_retention", "payer_conversion_d7", "roas_d7"):
            c, p = e.get(f"{m}_cur"), e.get(f"{m}_prev")
            e[f"{m}_pp"] = None if c is None or p is None else (c - p) * 100
    return out


# --------------------------------------------------------------------------------------
# Narrative
# --------------------------------------------------------------------------------------

def money(x: float) -> str:
    a = abs(x)
    s = f"${a / 1e6:.2f}M" if a >= 1e6 else f"${a / 1e3:.1f}k" if a >= 1e4 else f"${a:,.0f}"
    return f"-{s}" if x < 0 else s


def signed_money(x: float) -> str:
    return ("+" if x >= 0 else "") + money(x)


def fpct(x, digits=1) -> str:
    if x is None:
        return "n/a"
    if round(x * 100, digits) == 0:
        return f"{0:.{digits}f}%"
    return f"{x * 100:+.{digits}f}%"


def fpp(x) -> str:
    return "n/a" if x is None else f"{x:+.1f}pp"


def kfmt(n: float) -> str:
    return f"{n / 1e3:.1f}k" if abs(n) >= 1e4 else f"{n:,.0f}"


def entity(e) -> str:
    return e["key"] if e["dim"] == "channel" else f"{e['key']} (country)"


def pick_drivers(wow: dict) -> list[dict]:
    """One driver per lens (volume, efficiency, quality), each scored in USD, distinct entities.

    volume     : |Δspend|                          where budget moved
    efficiency : |ΔCPI × installs_cur|             extra/saved cost vs last week's CPI
    quality    : |ΔROAS D7 × D7-mature spend_cur|  D7 revenue gained/lost vs last week's ROAS
    """
    ents = [e for (dim, _), e in wow.items() if dim in ("channel", "country")]
    lenses = {
        "volume": lambda e: e["spend_cur"] - e["spend_prev"],
        "efficiency": lambda e: (e["cpi_cur"] - e["cpi_prev"]) * e["installs_cur"],
        "quality": lambda e: (e["roas_d7_cur"] - e["roas_d7_prev"]) * e["spend_d7_mature_cur"],
    }
    used, drivers = set(), []
    for lens, f in lenses.items():
        ranked = sorted(ents, key=lambda e: abs(f(e)), reverse=True)
        best = next((e for e in ranked if (e["dim"], e["key"]) not in used), ranked[0])
        used.add((best["dim"], best["key"]))
        drivers.append({"lens": lens, "entity": entity(best), "dim": best["dim"], "key": best["key"],
                        "impact_usd": f(best), "e": best})
    return drivers


def driver_text(d: dict) -> str:
    e, imp = d["e"], d["impact_usd"]
    name = entity(e)
    if d["lens"] == "volume":
        return (f"*Volume — {name}:* spend {signed_money(imp)} ({fpct(e['spend_pct'])}) to "
                f"{money(e['spend_cur'])}; installs {fpct(e['installs_pct'])} to {kfmt(e['installs_cur'])}.")
    if d["lens"] == "efficiency":
        verb = "cost an extra" if imp > 0 else "saved"
        return (f"*Efficiency — {name}:* CPI {fpct(e['cpi_pct'])} to ${e['cpi_cur']:.2f} "
                f"(IPM {fpct(e['ipm_pct'])}), {verb} ~{money(abs(imp))} vs last week's CPI.")
    verb = "added" if imp > 0 else "lost"
    return (f"*Quality — {name}:* D7 ROAS {fpp(e['roas_d7_pp'])} to {e['roas_d7_cur'] * 100:.1f}% "
            f"(D7 retention {fpp(e['d7_retention_pp'])}), {verb} ~{money(abs(imp))} of D7 revenue.")


def pick_action(wow: dict, checks, warnings) -> str:
    failed = [c for c in checks if not c[1]]
    if failed:
        return (f"Hold budget changes: {len(failed)} validation check(s) failed "
                f"({failed[0][0]}). Fix the data before acting on this report.")
    tot = wow[("total", "All paid")]
    blended = tot["roas_d7_cur"]
    chans = [e for (dim, _), e in wow.items() if dim == "channel"]
    trims = [e for e in chans if e["roas_d7_cur"] < blended * TRIM_BELOW]
    scales = [e for e in chans if e["roas_d7_cur"] > blended * SCALE_ABOVE
              and (e["roas_d7_pp"] or 0) >= 0 and (e["cpi_pct"] or 0) <= 0.05]
    trim = max(trims, key=lambda e: (blended - e["roas_d7_cur"]) * e["spend_cur"], default=None)
    scale = max(scales, key=lambda e: (e["roas_d7_cur"] - blended) * e["spend_cur"], default=None)

    caveat = ""
    if trim or scale:
        names = {x["key"] for x in (trim, scale) if x}
        flagged = sorted({w["date"] for w in warnings if w["channel"] in names and w["country"] == "all"})
        if flagged:
            ch = sorted({w["channel"] for w in warnings if w["channel"] in names and w["country"] == "all"})
            caveat = (f" First confirm the {'/'.join(ch)} day-level outlier(s) on {', '.join(flagged)} "
                      f"with the MMP.")

    if trim and scale:
        amt = trim["spend_cur"] * SHIFT_SHARE
        return (f"Shift ~{money(amt)}/wk ({SHIFT_SHARE:.0%} of {trim['key']}) from {trim['key']} "
                f"(D7 ROAS {trim['roas_d7_cur'] * 100:.1f}%) to {scale['key']} "
                f"({scale['roas_d7_cur'] * 100:.1f}%, blended {blended * 100:.1f}%), and check "
                f"{trim['key']} D30 payback before cutting further.{caveat}")
    if trim:
        return (f"Trim {trim['key']} by ~{money(trim['spend_cur'] * SHIFT_SHARE)}/wk: D7 ROAS "
                f"{trim['roas_d7_cur'] * 100:.1f}% vs {blended * 100:.1f}% blended; "
                f"check D30 payback before cutting further.{caveat}")
    if scale:
        return (f"Test +{SHIFT_SHARE:.0%} budget on {scale['key']}: D7 ROAS "
                f"{scale['roas_d7_cur'] * 100:.1f}% vs {blended * 100:.1f}% blended and improving, "
                f"CPI {fpct(scale['cpi_pct'])}.{caveat}")
    return (f"Hold budgets: no channel's D7 ROAS is far enough from the {blended * 100:.1f}% "
            f"blended rate to justify a shift.{caveat}")


def headline(wow: dict, organic) -> str:
    t = wow[("total", "All paid")]
    org = {r["period"]: r["installs"] for r in organic}
    return (f"Paid UA spent {money(t['spend_cur'])} ({fpct(t['spend_pct'])} WoW) for "
            f"{kfmt(t['installs_cur'])} installs ({fpct(t['installs_pct'])}); blended CPI "
            f"${t['cpi_cur']:.2f} ({fpct(t['cpi_pct'])}), D7 ROAS {t['roas_d7_cur'] * 100:.1f}% "
            f"({fpp(t['roas_d7_pp'])}). Organic installs {fpct(pct(org['cur'], org['prev']))}.")


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------

def table_rows(wow: dict, dim: str, order: list[str]) -> list[dict]:
    keys = [k for k in order if (dim, k) in wow] + sorted(
        k for (d, k) in wow if d == dim and k not in order)
    return [wow[(dim, k)] for k in keys]


def compact_table(wow: dict) -> str:
    hdr = f"{'':<9}{'Spend':>7}{'Δ':>7}{'Inst':>7}{'Δ':>7}{'CPI':>6}{'Δ':>7}{'ROAS7':>7}{'Δpp':>6}"
    lines = [hdr]

    def line(e, label):
        return (f"{label:<9}{money(e['spend_cur']):>7}{fpct(e['spend_pct'], 0):>7}"
                f"{kfmt(e['installs_cur']):>7}{fpct(e['installs_pct'], 0):>7}"
                f"{e['cpi_cur']:>6.2f}{fpct(e['cpi_pct'], 0):>7}"
                f"{e['roas_d7_cur'] * 100:>6.1f}%{e['roas_d7_pp']:>+6.1f}")

    for e in table_rows(wow, "channel", CHANNEL_ORDER):
        lines.append(line(e, e["key"]))
    lines.append("-" * len(hdr))
    for e in table_rows(wow, "country", COUNTRY_ORDER):
        lines.append(line(e, e["key"]))
    lines.append("-" * len(hdr))
    lines.append(line(wow[("total", "All paid")], "Paid"))
    return "\n".join(lines)


def windows(week_start: date, wow: dict) -> dict:
    t = wow[("total", "All paid")]
    we = week_start + timedelta(days=6)
    ps, pe = week_start - timedelta(days=7), week_start - timedelta(days=1)
    return {
        "week": f"{week_start} → {we}",
        "prev_week": f"{ps} → {pe}",
        "delivery": f"activity dates {week_start} → {we} vs {ps} → {pe}",
        "d7": f"installs {week_start} → {t['d7_max_install_date_cur']} vs {ps} → "
              f"{t['d7_max_install_date_prev']} (D7-mature cohorts only)",
    }


def slack_text(week_start, wow, organic, drivers, action, checks, warnings) -> str:
    w = windows(week_start, wow)
    failed = [c for c in checks if not c[1]]
    status = (f":white_check_mark: {len(checks)}/{len(checks)} validation checks passed"
              if not failed else f":warning: {len(failed)} validation check(s) FAILED")
    if warnings:
        status += f"; {len(warnings)} day-level outlier(s) flagged"
    lines = [
        f"*Dice Kingdom — Weekly UA report* ({w['week']}, Mon–Sun)",
        "",
        f":dart: *{headline(wow, organic)}*",
        "",
        "*Drivers*",
        *[f"• {driver_text(d)}" for d in drivers],
        "",
        f":point_right: *Action:* {action}",
        "",
        "```\n" + compact_table(wow) + "\n```",
        f"_Paid only. Spend/installs/CPI: {w['delivery']}. D7 ROAS: {w['d7']}._",
        f"_{status}._",
    ]
    return "\n".join(lines)


def markdown_report(week_start, as_of, wow, organic, kpis, drivers, action, checks, warnings) -> str:
    w = windows(week_start, wow)
    k = {r["period"]: r for r in kpis}
    org = {r["period"]: r["installs"] for r in organic}

    def mdtable(dim, order):
        rows = ["| | Spend | Δ | Installs | Δ | CPI | Δ | CTR | IPM | D1 ret | D7 ret | Δpp | "
                "Payer conv D7 | D7 ROAS | Δpp |",
                "|---|" + "---:|" * 15]
        for e in table_rows(wow, dim, order) + [wow[("total", "All paid")]]:
            rows.append(
                f"| {e['key']} | {money(e['spend_cur'])} | {fpct(e['spend_pct'])} | "
                f"{e['installs_cur']:,.0f} | {fpct(e['installs_pct'])} | ${e['cpi_cur']:.3f} | "
                f"{fpct(e['cpi_pct'])} | {e['ctr_cur'] * 100:.2f}% | {e['ipm_cur']:.2f} | "
                f"{e['d1_retention_cur'] * 100:.1f}% | {e['d7_retention_cur'] * 100:.1f}% | "
                f"{fpp(e['d7_retention_pp'])} | {e['payer_conversion_d7_cur'] * 100:.2f}% | "
                f"{e['roas_d7_cur'] * 100:.1f}% | {fpp(e['roas_d7_pp'])} |")
        return "\n".join(rows)

    out = [
        f"# Dice Kingdom weekly UA report: {w['week']}",
        "",
        f"Data as-of {as_of}. Previous week {w['prev_week']}.",
        "",
        "**Date windows**",
        f"- Spend, installs, CPI, CTR, IPM: {w['delivery']} (paid only)",
        f"- D1 retention: installs {week_start} → {week_start + timedelta(days=6)} (all D1-mature)",
        f"- D7 retention, D7 payer conversion, D7 ROAS: {w['d7']}",
        f"- Game KPIs (ARPDAU, daily payer rate): {w['delivery']} (all users, paid + organic)",
        "",
        "## Summary",
        "",
        f"**{headline(wow, organic)}**",
        "",
        *[f"{i}. {driver_text(d).replace('*', '**')}" for i, d in enumerate(drivers, 1)],
        "",
        f"**Recommended action:** {action}",
        "",
        "## By channel (paid)",
        "",
        mdtable("channel", CHANNEL_ORDER),
        "",
        "## By country (paid)",
        "",
        mdtable("country", COUNTRY_ORDER),
        "",
        "## Game-wide context (daily_kpis, all users)",
        "",
        "| | This week | Prev week | Δ |",
        "|---|---:|---:|---:|",
        f"| Revenue | {money(k['cur']['revenue'])} | {money(k['prev']['revenue'])} | "
        f"{fpct(pct(k['cur']['revenue'], k['prev']['revenue']))} |",
        f"| Avg DAU | {k['cur']['avg_dau']:,.0f} | {k['prev']['avg_dau']:,.0f} | "
        f"{fpct(pct(k['cur']['avg_dau'], k['prev']['avg_dau']))} |",
        f"| ARPDAU | ${k['cur']['arpdau']:.4f} | ${k['prev']['arpdau']:.4f} | "
        f"{fpct(pct(k['cur']['arpdau'], k['prev']['arpdau']))} |",
        f"| Daily payer rate | {k['cur']['daily_payer_rate'] * 100:.2f}% | "
        f"{k['prev']['daily_payer_rate'] * 100:.2f}% | "
        f"{fpp((k['cur']['daily_payer_rate'] - k['prev']['daily_payer_rate']) * 100)} |",
        f"| Organic installs | {org['cur']:,.0f} | {org['prev']:,.0f} | "
        f"{fpct(pct(org['cur'], org['prev']))} |",
        "",
        "## Validation",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
        *[f"| {n} | {'PASS' if ok else '**FAIL**'} | {d} |" for n, ok, d in checks],
        "",
        f"### Outlier flags ({len(warnings)})",
        "",
        "Current-week channel-day and channel×country-day values with |robust z| ≥ 3.5 vs the "
        "trailing 28 days. Flags, not errors: confirm before acting.",
        "",
        *([f"- {w_['label']}" for w_ in warnings] or ["- none"]),
        "",
    ]
    return "\n".join(out)


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--week", help="any date in the report week (YYYY-MM-DD); default last complete week")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    ap.add_argument("--post", action="store_true", help="post the Slack summary via scripts/post_to_slack.py")
    ap.add_argument("--force-post", action="store_true", help="post even if validation failed")
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=True)
    try:
        week_start, as_of, _ = resolve_week(con, args.week)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    params = {"week_start": week_start.isoformat(), "as_of": as_of.isoformat()}
    delivery = run_sql(con, "paid_delivery.sql", params)
    quality = run_sql(con, "paid_cohort_quality.sql", params)
    organic = run_sql(con, "organic_installs.sql", params)
    kpis = run_sql(con, "game_kpis.sql", params)
    reconcile = run_sql(con, "check_reconcile.sql", params)
    nulls = run_sql(con, "check_nulls.sql", params)
    outliers = run_sql(con, "check_outliers.sql", params)
    con.close()

    checks, warnings = validate(delivery, quality, reconcile, nulls, outliers, organic, kpis)
    wow = wow_table(delivery, quality)
    drivers = pick_drivers(wow)
    action = pick_action(wow, checks, warnings)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"weekly_ua_{week_start}"
    slack = slack_text(week_start, wow, organic, drivers, action, checks, warnings)
    stem.with_suffix(".slack").write_text(slack + "\n")
    stem.with_suffix(".md").write_text(
        markdown_report(week_start, as_of, wow, organic, kpis, drivers, action, checks, warnings))
    stem.with_suffix(".json").write_text(json.dumps({
        "week_start": week_start.isoformat(), "as_of": as_of.isoformat(),
        "windows": windows(week_start, wow),
        "checks": [{"check": n, "passed": ok, "detail": d} for n, ok, d in checks],
        "outliers": warnings,
        "wow": [v for v in wow.values()],
        "drivers": [{k: v for k, v in d.items() if k != "e"} for d in drivers],
        "action": action,
        "organic": organic, "game_kpis": kpis,
    }, indent=2, default=str) + "\n")

    failed = [c for c in checks if not c[1]]
    print(f"week {week_start} → {week_start + timedelta(days=6)} (as-of {as_of})")
    print(f"validation: {len(checks) - len(failed)}/{len(checks)} passed, {len(warnings)} outlier flag(s)")
    for n, _, d in failed:
        print(f"  FAIL {n}: {d}")
    print(f"wrote {stem}.md, .slack, .json\n")
    print(slack)

    if args.post:
        if failed and not args.force_post:
            print("\nnot posting: validation failed (use --force-post to override)", file=sys.stderr)
            return 1
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "post_to_slack.py"),
                            str(stem.with_suffix(".slack"))])
        if r.returncode != 0:
            return r.returncode
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

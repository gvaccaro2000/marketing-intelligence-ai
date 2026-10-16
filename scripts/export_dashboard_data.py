"""Export weekly UA dashboard data for Dice Kingdom.

Runs the vetted SQL in sql/weekly_ua/ (dashboard_weekly.sql, dashboard_checks.sql) against
data/marketing.duckdb, validates the numbers and writes CSVs to reports/dashboard/:

  weekly_total.csv     week_start, spend, installs, cpi, d7_revenue, d7_mature_spend, roas_d7,
                       organic_installs
  weekly_channel.csv   same metrics by paid channel (no organic_installs: Organic is not a paid
                       channel; its installs are in weekly_total / weekly_country)
  weekly_country.csv   same metrics by country (organic_installs = that country's Organic installs)
  latest_channel.csv   latest complete week by channel: spend, installs, cpi, roas_d7, spend_share,
  latest_country.csv   spend_wow, cpi_wow, roas_d7_wow_pp (same columns by country)

Only complete Mon-Sun weeks (all 7 days in ua_spend). Spend, installs, CPI: paid only, activity
dates. D7 revenue / spend / ROAS: D7-mature cohorts only (install_date <= as_of - 7), in numerator
and denominator, so the latest week's D7 figures can cover fewer than 7 install days.
Shares and WoW changes are fractions (0.05 = 5%); roas_d7_wow_pp is in percentage points.

Usage:
  python scripts/export_dashboard_data.py [--db PATH] [--out-dir DIR]

Exit codes: 0 ok, 1 validation failed (nothing written).
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql" / "weekly_ua"
DEFAULT_DB = ROOT / "data" / "marketing.duckdb"
DEFAULT_OUT = ROOT / "reports" / "dashboard"

CHANNEL_ORDER = ["Meta", "Google", "AppLovin", "TikTok", "Unity"]
COUNTRY_ORDER = ["US", "UK", "DE", "FR", "JP", "BR"]
MONEY_TOL = 0.01  # reconciliation tolerance in USD

SUMMED = ["spend", "installs", "d7_revenue", "d7_mature_spend", "organic_installs"]
WEEKLY_COLS = ["spend", "installs", "cpi", "d7_revenue", "d7_mature_spend", "roas_d7"]
LATEST_COLS = ["spend", "installs", "cpi", "roas_d7", "spend_share", "spend_wow", "cpi_wow",
               "roas_d7_wow_pp"]
DIGITS = {"spend": 2, "d7_revenue": 2, "d7_mature_spend": 2, "cpi": 4, "roas_d7": 6,
          "spend_share": 6, "spend_wow": 6, "cpi_wow": 6, "roas_d7_wow_pp": 4}


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


def close(a, b, tol=MONEY_TOL) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def ratio(n, d):
    return None if n is None or not d else n / d


def change(cur, prev):
    return None if cur is None or not prev else cur / prev - 1


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------

def validate(weekly: list[dict], chk: dict, as_of: date) -> list[tuple[str, bool, str]]:
    checks = []
    totals = {r["week_start"]: r for r in weekly if r["dim"] == "total"}
    weeks = sorted(totals)

    consecutive = all(date.fromisoformat(b) - date.fromisoformat(a) == timedelta(days=7)
                      for a, b in zip(weeks, weeks[1:]))
    checks.append(("complete weeks", len(weeks) == chk["complete_weeks"] and len(weeks) >= 2
                   and consecutive,
                   f"{len(weeks)} weeks {weeks[0] if weeks else '-'} → {weeks[-1] if weeks else '-'}, "
                   f"consecutive={consecutive} (need ≥ 2 for WoW)"))

    bad = chk["rows_only_in_cohorts"] + chk["rows_only_in_ua_spend"] + chk["rows_install_mismatch"]
    checks.append(("ua_spend → cohort grain = cohorts.installs",
                   bad == 0 and chk["ua_installs"] == chk["cohort_installs"],
                   f"{chk['grain_rows']} rows, {bad} mismatched; installs "
                   f"{chk['ua_installs']:,} vs {chk['cohort_installs']:,}"))

    fan = [r for r in weekly
           if not close(r["join_spend"], r["spend"]) or r["join_installs"] != r["installs"]]
    checks.append(("cohort join keeps paid spend + installs (no fan-out)", not fan,
                   f"{len(fan)} of {len(weekly)} rows differ"))

    for dim in ("channel", "country"):
        off = []
        for w in weeks:
            parts = [r for r in weekly if r["dim"] == dim and r["week_start"] == w]
            for m in SUMMED:
                s = sum(r[m] for r in parts)
                if not close(s, totals[w][m]):
                    off.append(f"{w} {m} {s:.2f} vs {totals[w][m]:.2f}")
        checks.append((f"{dim} rows sum to weekly total", not off,
                       "; ".join(off[:3]) or f"{len(weeks)} weeks × {len(SUMMED)} metrics"))

    last_mature = (as_of - timedelta(days=7)).isoformat()
    late = [r for r in weekly if r["d7_max_install_date"] and r["d7_max_install_date"] > last_mature]
    over = [r for r in weekly if r["d7_mature_spend"] > r["spend"] + MONEY_TOL]
    checks.append(("D7 uses mature cohorts only",
                   not late and not over and chk["d7_missing_mature"] == 0
                   and chk["d7_present_immature"] == 0,
                   f"last D7-mature install date {last_mature}; {chk['d7_missing_mature']} mature "
                   f"cohorts missing D7, {chk['d7_present_immature']} immature with D7, "
                   f"{len(over)} rows with D7 spend > spend"))
    return checks


# --------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------

def fmt(col: str, v):
    if v is None:
        return ""
    if col in DIGITS:
        return f"{v:.{DIGITS[col]}f}"
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow([fmt(c, r.get(c)) for c in header])


def ordered(weekly: list[dict], dim: str, order: list[str]) -> list[dict]:
    rows = [r for r in weekly if r["dim"] == dim and r["key"] in order]
    return sorted(rows, key=lambda r: (r["week_start"], order.index(r["key"])))


def latest(weekly: list[dict], dim: str, order: list[str], week: str, prev: str) -> list[dict]:
    total = next(r for r in weekly if r["dim"] == "total" and r["week_start"] == week)
    by = {(r["key"], r["week_start"]): r for r in weekly if r["dim"] == dim}
    out = []
    for k in order:
        cur, p = by.get((k, week)), by.get((k, prev))
        if cur is None:
            continue
        p = p or {}
        out.append({
            dim: k,
            "spend": cur["spend"], "installs": cur["installs"], "cpi": cur["cpi"],
            "roas_d7": cur["roas_d7"],
            "spend_share": ratio(cur["spend"], total["spend"]),
            "spend_wow": change(cur["spend"], p.get("spend")),
            "cpi_wow": change(cur["cpi"], p.get("cpi")),
            "roas_d7_wow_pp": (None if cur["roas_d7"] is None or p.get("roas_d7") is None
                               else (cur["roas_d7"] - p["roas_d7"]) * 100),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=True)
    as_of = con.execute("SELECT MAX(date) FROM ua_spend").fetchone()[0]
    params = {"as_of": as_of.isoformat()}
    weekly = run_sql(con, "dashboard_weekly.sql", params)
    chk = run_sql(con, "dashboard_checks.sql", params)[0]
    con.close()

    checks = validate(weekly, chk, as_of)
    failed = [c for c in checks if not c[1]]
    print(f"validation: {len(checks) - len(failed)}/{len(checks)} passed")
    for n, ok, d in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {n}: {d}")
    if failed:
        print("not writing dashboard data: validation failed", file=sys.stderr)
        return 1

    weeks = sorted(r["week_start"] for r in weekly if r["dim"] == "total")
    week, prev = weeks[-1], weeks[-2]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    write_csv(out / "weekly_total.csv", ["week_start", *WEEKLY_COLS, "organic_installs"],
              sorted((r for r in weekly if r["dim"] == "total"), key=lambda r: r["week_start"]))
    for dim, order, extra in (("channel", CHANNEL_ORDER, []),
                              ("country", COUNTRY_ORDER, ["organic_installs"])):
        rows = [{**r, dim: r["key"]} for r in ordered(weekly, dim, order)]
        write_csv(out / f"weekly_{dim}.csv", ["week_start", dim, *WEEKLY_COLS, *extra], rows)
        write_csv(out / f"latest_{dim}.csv", [dim, *LATEST_COLS],
                  latest(weekly, dim, order, week, prev))

    week_end = date.fromisoformat(week) + timedelta(days=6)
    print(f"weeks {weeks[0]} → {week_end} ({len(weeks)} complete weeks, data as-of {as_of})")
    print(f"latest week {week} → {week_end} vs {prev}; "
          f"D7 metrics: installs through {as_of - timedelta(days=7)} (D7-mature only)")
    print(f"wrote {out}/weekly_{{total,channel,country}}.csv, latest_{{channel,country}}.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())

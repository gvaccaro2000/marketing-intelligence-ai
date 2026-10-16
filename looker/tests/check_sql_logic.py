"""Run the LookML CPI and D7 ROAS measures against DuckDB and compare them with the weekly report.

The LookML is rendered to SQL (lookml_sql.py), pointed at data/marketing.duckdb attached as
`marketing` (so `marketing.ua_spend` etc. resolve as they would in Redshift), and compared by
channel with the vetted weekly-report queries in sql/weekly_ua/ for the same Monday-Sunday week.

    python looker/tests/check_sql_logic.py [--week 2026-08-10]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lookml_sql import Renderer, load_model  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "data" / "marketing.duckdb"
WEEKLY_SQL = REPO / "sql" / "weekly_ua"
TOL = 1e-9


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"ATTACH '{DB}' AS marketing (READ_ONLY)")
    con.execute("USE marketing")
    return con


def explore(name: str) -> dict:
    return next(e for e in load_model()["explores"] if e["name"] == name)


def run_vetted(con, file: str, params: dict) -> list[dict]:
    sql = (WEEKLY_SQL / file).read_text()
    used = {k: v for k, v in params.items() if re.search(rf"\${k}\b", sql)}
    cur = con.execute(sql, used)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def lookml_by_channel(con, week: str) -> dict[str, dict]:
    """CPI (ua_spend view and spend_cohort_grain view) and D7 ROAS by channel, one week."""
    r = Renderer()
    out: dict[str, dict] = {}
    q1 = r.query(explore("ua_spend"), ["ua_spend.channel"], ["ua_spend.spend", "ua_spend.cpi"],
                 f"${{ua_spend.date_week}} = DATE '{week}'")
    for ch, spend, cpi in con.execute(q1).fetchall():
        out.setdefault(ch, {}).update(spend=spend, cpi=cpi)
    q2 = r.query(explore("ua_performance"), ["cohorts.channel"],
                 ["spend_cohort_grain.cpi", "cohorts.roas_d7", "cohorts.spend_d7_mature"],
                 f"${{cohorts.install_week}} = DATE '{week}'")
    for ch, cpi_cg, roas, spend_m in con.execute(q2).fetchall():
        out.setdefault(ch, {}).update(cpi_cohort_grain=cpi_cg, roas_d7=roas, spend_d7_mature=spend_m)
    return out


def report_by_channel(con, week: str) -> dict[str, dict]:
    as_of = con.execute("SELECT MAX(date) FROM ua_spend").fetchone()[0]
    params = {"week_start": week, "as_of": as_of}
    out: dict[str, dict] = {}
    for row in run_vetted(con, "paid_delivery.sql", params):
        if row["dim"] == "channel" and row["period"] == "cur":
            out.setdefault(row["key"], {})["cpi"] = row["cpi"]
    for row in run_vetted(con, "paid_cohort_quality.sql", params):
        if row["dim"] == "channel" and row["period"] == "cur":
            out.setdefault(row["key"], {}).update(roas_d7=row["roas_d7"], spend_d7_mature=row["spend_d7_mature"])
    return out


def compare(week: str) -> list[tuple]:
    """Rows of (channel, metric, lookml, report, ok)."""
    con = connect()
    lk, rep = lookml_by_channel(con, week), report_by_channel(con, week)
    rows = []
    for ch in sorted(set(lk) | set(rep)):
        a, b = lk.get(ch, {}), rep.get(ch, {})
        for metric, ref in [("cpi", "cpi"), ("cpi_cohort_grain", "cpi"), ("roas_d7", "roas_d7")]:
            x, y = a.get(metric), b.get(ref)
            ok = x is not None and y is not None and abs(float(x) - float(y)) <= TOL
            # Organic has no spend: the LookML returns NULL, and the paid report has no row.
            if ch == "Organic" and x is None and y is None:
                ok = True
            rows.append((ch, metric, x, y, ok))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", default="2026-08-10", help="Monday of the week")
    week = ap.parse_args().week
    rows = compare(week)
    print(f"Week {week} (installs/activity {week} -> +6 days), LookML vs sql/weekly_ua report, by channel")
    print(f"{'channel':<10}{'metric':<18}{'lookml':>14}{'report':>14}  ok")
    fmt = lambda v: "NULL" if v is None else f"{float(v):.6f}"
    for ch, m, x, y, ok in rows:
        print(f"{ch:<10}{m:<18}{fmt(x):>14}{fmt(y):>14}  {'PASS' if ok else 'FAIL'}")
    return 0 if all(r[-1] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())

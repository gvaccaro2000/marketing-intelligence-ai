"""Weekly UA report for Dice Kingdom.

Runs the vetted SQL in sql/weekly_ua/ against data/marketing.duckdb, validates the numbers,
computes week-over-week (WoW) changes per channel and per country, and writes:

  reports/weekly_ua_<week_start>.md      full report (validation log, channel + country tables)
  reports/weekly_ua_<week_start>.slack   Slack mrkdwn summary (headline, structural issues, 1 action, WoW line)
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

# Structural issues: each channel/country vs the rest of paid (paid total minus itself) and vs its
# own trailing weeks. Week-over-week deltas hide problems that have been there for a while.
STRUCT_WEEKS = 8        # report week + 7 trailing weeks
RECENT_WEEKS = 4        # "now" = last 4 weeks; "before" = the weeks before them
FAR_BELOW = 0.80        # weekly D7 ROAS below 80% of rest-of-paid D7 ROAS ...
PERSIST_WEEKS = 4       # ... in every one of the last >= 4 weeks -> persistent gap
CPI_ABOVE = 1.25        # CPI above 125% of rest of paid (context on flagged entities)
STEP_CHANGE = 0.15      # D7 ROAS down >= 15% after a split week vs before it ...
STEP_MIN_WEEKS = 2      # ... >= 2 weeks each side, every week after below the before level
SHARE_DRIFT_PP = 3.0    # budget share up >= 3pp (last 4 wks vs before) while ROAS < rest of paid
MIN_IMPACT_USD = 1000   # weekly D7 revenue at stake below which an issue isn't reported
STRUCT_SHIFT = 0.25     # suggested move out of a persistently low-ROAS entity: 25% of its spend


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


def validate(delivery, quality, reconcile, nulls, outliers, organic, kpis, weekly,
             week_start: date) -> tuple[list, list]:
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

    # 4. structural weekly series: breakdowns sum to totals, full weeks, ties out to the WoW queries
    weeks = sorted({r["week_start"] for r in weekly if r["dim"] == "total"})
    first = max(week_start - timedelta(weeks=STRUCT_WEEKS - 1),
                week_start - timedelta(weeks=len(weeks) - 1))
    exp = [(first + timedelta(weeks=i)).isoformat() for i in range((week_start - first).days // 7 + 1)]
    checks.append(("[structural] weekly series covers consecutive full weeks", weeks == exp and all(
        r["days"] == 7 for r in weekly if r["dim"] == "total"), f"{len(weeks)} weeks {weeks[0]} → {weeks[-1]}"))
    bad = []
    for wk in weeks:
        tot = next(r for r in weekly if r["dim"] == "total" and r["week_start"] == wk)
        for dim in ("channel", "country"):
            parts = [r for r in weekly if r["dim"] == dim and r["week_start"] == wk]
            bad += [f"{wk} {dim} {c}" for c in ("spend", "installs", "revenue_d7", "spend_d7")
                    if not close(sum(x[c] or 0 for x in parts), tot[c] or 0)]
    checks.append(("[structural] channel and country rows sum to weekly totals", not bad,
                   "ok" if not bad else "; ".join(bad[:3])))
    wk_tot = {r["week_start"]: r for r in weekly if r["dim"] == "total"}
    cur_w, prev_w = week_start.isoformat(), (week_start - timedelta(days=7)).isoformat()
    bad = []
    for p, wk in (("cur", cur_w), ("prev", prev_w)):
        d = next(r for r in delivery if r["dim"] == "total" and r["period"] == p)
        q = next(r for r in quality if r["dim"] == "total" and r["period"] == p)
        t = wk_tot.get(wk)
        if not (t and close(t["spend"], d["spend"]) and t["installs"] == d["installs"]
                and close(t["revenue_d7"], q["revenue_d7_mature"])
                and close(t["spend_d7"], q["spend_d7_mature"])):
            bad.append(p)
    checks.append(("[structural] report + previous week tie out to WoW totals", not bad,
                   "ok (spend, installs, D7-mature revenue and spend)" if not bad
                   else f"mismatch in {', '.join(bad)}"))

    # 5. NULL / impossible-value checks
    for r in nulls:
        checks.append((r["check_name"], r["failures"] == 0, f"{r['failures']} failing rows"))

    # 6. outliers are warnings, not failures
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
# Structural issues (vs rest of paid, vs own trailing weeks)
# --------------------------------------------------------------------------------------

COMPS = ("spend", "installs", "revenue_d7", "spend_d7", "revenue_d30", "spend_d30")


def ratio(n, d):
    return None if n is None or not d else n / d


def agg(weeks: list[dict], side: str = "") -> dict:
    """Sum components over weeks (side '' = entity, 'rest_' = rest of paid) and derive ratios."""
    t = {c: sum(w[f"{side}{c}"] for w in weeks) for c in COMPS}
    t["total_spend"] = sum(w["total_spend"] for w in weeks)
    t["roas7"] = ratio(t["revenue_d7"], t["spend_d7"])
    t["roas30"] = ratio(t["revenue_d30"], t["spend_d30"])
    t["cpi"] = ratio(t["spend"], t["installs"])
    t["share"] = ratio(t["spend"], t["total_spend"])
    t["spend_wk"] = t["spend"] / len(weeks)
    return t


def structural_series(rows: list[dict]) -> tuple[list[str], dict]:
    """{(dim, key): [per-week dict with entity and rest-of-paid components]} over the weeks present."""
    weeks = sorted({r["week_start"] for r in rows if r["dim"] == "total"})
    by = {(r["dim"], r["key"], r["week_start"]): r for r in rows}
    ents = sorted({(r["dim"], r["key"]) for r in rows if r["dim"] != "total"})
    series = {}
    for dim, key in ents:
        s = []
        for wk in weeks:
            t = by[("total", "All paid", wk)]
            r = by.get((dim, key, wk), {})
            w = {"week": wk, "total_spend": t["spend"]}
            for c in COMPS:
                v, tv = r.get(c) or 0, t[c] or 0
                w[c], w[f"rest_{c}"] = v, tv - v
            w["roas7"] = ratio(w["revenue_d7"], w["spend_d7"])
            w["rest_roas7"] = ratio(w["rest_revenue_d7"], w["rest_spend_d7"])
            s.append(w)
        series[(dim, key)] = s
    return weeks, series


def analyse_entity(dim: str, key: str, s: list[dict]) -> dict:
    n = len(s)
    recent, before = s[-RECENT_WEEKS:], s[:-RECENT_WEEKS]
    a = {"dim": dim, "key": key, "weeks": n, "now": agg(recent), "rest_now": agg(recent, "rest_"),
         "all": agg(s), "rest_all": agg(s, "rest_"),
         "share_before": agg(before)["share"] if before else None,
         "weekly_roas7": [w["roas7"] for w in s], "weekly_rest_roas7": [w["rest_roas7"] for w in s]}
    now, rest = a["now"], a["rest_now"]
    a["roas_idx"] = ratio(now["roas7"], rest["roas7"])
    a["cpi_idx"] = ratio(now["cpi"], rest["cpi"])

    # 1. Persistent gap: below FAR_BELOW x rest of paid in each of the last >= PERSIST_WEEKS weeks.
    streak = 0
    for w in reversed(s):
        if w["roas7"] is None or w["rest_roas7"] is None or w["roas7"] >= FAR_BELOW * w["rest_roas7"]:
            break
        streak += 1
    a["streak"] = streak
    a["persistent"] = streak >= PERSIST_WEEKS
    a["gap_usd"] = (rest["roas7"] - now["roas7"]) * now["spend_wk"] if a["persistent"] else 0.0

    # 2. Step change vs own history: best split with every week after it below the level before it.
    best = None
    for k in range(STEP_MIN_WEEKS, n - STEP_MIN_WEEKS + 1):
        b, af = agg(s[:k]), agg(s[k:])
        if not b["roas7"] or af["roas7"] is None:
            continue
        if not all(w["roas7"] is not None and w["roas7"] < b["roas7"] for w in s[k:]):
            continue
        chg = af["roas7"] / b["roas7"] - 1
        if best is None or chg < best["chg"]:
            best = {"week": s[k]["week"], "chg": chg, "before": b, "after": af}
    a["step"] = best if best and best["chg"] <= -STEP_CHANGE else None
    a["step_usd"] = ((best["before"]["roas7"] - best["after"]["roas7"]) * best["after"]["spend_wk"]
                     if a["step"] else 0.0)

    # 3. Budget drift: share up >= SHARE_DRIFT_PP while D7 ROAS is below the rest of paid.
    a["share_pp"] = None if a["share_before"] is None else (now["share"] - a["share_before"]) * 100
    a["drift"] = bool(a["share_pp"] is not None and a["share_pp"] >= SHARE_DRIFT_PP
                      and now["roas7"] is not None and now["roas7"] < rest["roas7"])
    extra_wk = (now["share"] - (a["share_before"] or 0)) * now["total_spend"] / len(recent)
    a["drift_usd"] = (rest["roas7"] - now["roas7"]) * extra_wk if a["drift"] else 0.0

    a["impact_usd"] = max(a["gap_usd"], a["step_usd"], a["drift_usd"])
    a["flagged"] = a["impact_usd"] >= MIN_IMPACT_USD
    a["action"] = structural_action(a) if a["flagged"] else None
    return a


def structural_action(a: dict) -> dict:
    """Candidate action for one flagged entity, scored in D7 revenue per week."""
    name, now, rest = a["key"], a["now"], a["rest_now"]
    cands = []
    if a["step"]:
        st = a["step"]
        cands.append({"usd": a["step_usd"], "text": (
            f"Diagnose {name}'s drop since w/c {st['week']} (D7 ROAS {pct1(st['before']['roas7'])} → "
            f"{pct1(st['after']['roas7'])}, CPI ${st['before']['cpi']:.2f} → ${st['after']['cpi']:.2f}) "
            f"with the partner/MMP: getting back to its prior level is worth ~{money(a['step_usd'])}/wk "
            f"of D7 revenue. If it isn't explained within a week, cut {name} by {STRUCT_SHIFT:.0%} "
            f"(~{money(now['spend_wk'] * STRUCT_SHIFT)}/wk).")})
        # a persistent gap that started with the step is the same problem: fix the cause first
        cands[-1]["usd"] = max(cands[-1]["usd"], a["gap_usd"])
    if a["persistent"]:
        amt = now["spend_wk"] * STRUCT_SHIFT
        usd = amt * (rest["roas7"] - now["roas7"])
        d30 = ""
        if a["all"]["roas30"] is not None and a["rest_all"]["roas30"]:
            d30 = (f" D30 doesn't close the gap ({pct1(a['all']['roas30'])} vs "
                   f"{pct1(a['rest_all']['roas30'])}).")
        cands.append({"usd": usd, "text": (
            f"Move {STRUCT_SHIFT:.0%} of {name} spend (~{money(amt)}/wk) into the rest of paid "
            f"(D7 ROAS {pct1(rest['roas7'])} vs {pct1(now['roas7'])}): ~+{money(usd)}/wk of D7 "
            f"revenue at average returns.{d30}")})
    if a["drift"]:
        cands.append({"usd": a["drift_usd"], "text": (
            f"Cap {name} at its earlier {pct1(a['share_before'], 0)} budget share (now "
            f"{pct1(now['share'], 0)}) and return the difference to the rest of paid: "
            f"~+{money(a['drift_usd'])}/wk of D7 revenue.")})
    best = max(cands, key=lambda c: c["usd"])
    return {**best, "at_stake_usd": a["impact_usd"], "source": "structural", "entity": name,
            "dim": a["dim"], "key": a["key"]}


def structural_issues(rows: list[dict]) -> dict:
    weeks, series = structural_series(rows)
    if len(weeks) < RECENT_WEEKS + STEP_MIN_WEEKS:
        return {"weeks": weeks, "entities": [], "issues": [], "skipped": True, "rows": rows}
    ents = [analyse_entity(dim, key, s) for (dim, key), s in series.items()]
    issues = sorted((a for a in ents if a["flagged"]), key=lambda a: a["impact_usd"], reverse=True)
    return {"weeks": weeks, "entities": ents, "issues": issues, "skipped": False, "rows": rows}


def issue_text(a: dict) -> str:
    """One line per flagged entity: what is wrong, since when, and the weekly D7 revenue at stake."""
    now, rest = a["now"], a["rest_now"]
    parts = []
    if a["step"]:
        st = a["step"]
        parts.append(f"step change w/c {st['week'][5:]}: D7 ROAS {pct1(st['before']['roas7'])} → "
                     f"{pct1(st['after']['roas7'])}, CPI {fpct(ratio(st['after']['cpi'], st['before']['cpi']) - 1, 0)}")
    if a["persistent"]:
        streak = f"{a['streak']}{'+' if a['streak'] == a['weeks'] else ''}"
        parts.append(f"D7 ROAS {pct1(now['roas7'])} vs {pct1(rest['roas7'])} rest of paid, "
                     f"<{FAR_BELOW:.0%} of it for {streak} wks")
    elif a["step"]:
        parts.append(f"now {pct1(now['roas7'])} vs {pct1(rest['roas7'])} rest of paid")
    if not a["step"] and a["cpi_idx"] and a["cpi_idx"] > CPI_ABOVE and (a["roas_idx"] or 0) < 1:
        parts.append(f"CPI ${now['cpi']:.2f} vs ${rest['cpi']:.2f}")
    share = f"{pct1(now['share'], 0)} of spend"
    if a["share_pp"] is not None and abs(a["share_pp"]) >= SHARE_DRIFT_PP:
        share += f" (was {pct1(a['share_before'], 0)})"
    parts.append(share)
    return f"*{entity(a)}* — {'; '.join(parts)}. *~{money(a['impact_usd'])}/wk*"


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


def pct1(x, digits=1) -> str:
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


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


def wow_action(wow: dict) -> dict | None:
    """This week's ROAS-vs-blended candidate action, scored in D7 revenue per week."""
    tot = wow[("total", "All paid")]
    blended = tot["roas_d7_cur"]
    chans = [e for (dim, _), e in wow.items() if dim == "channel"]
    trims = [e for e in chans if e["roas_d7_cur"] < blended * TRIM_BELOW]
    scales = [e for e in chans if e["roas_d7_cur"] > blended * SCALE_ABOVE
              and (e["roas_d7_pp"] or 0) >= 0 and (e["cpi_pct"] or 0) <= 0.05]
    trim = max(trims, key=lambda e: (blended - e["roas_d7_cur"]) * e["spend_cur"], default=None)
    scale = max(scales, key=lambda e: (e["roas_d7_cur"] - blended) * e["spend_cur"], default=None)

    if trim and scale:
        amt = trim["spend_cur"] * SHIFT_SHARE
        usd = amt * (scale["roas_d7_cur"] - trim["roas_d7_cur"])
        text = (f"Shift ~{money(amt)}/wk ({SHIFT_SHARE:.0%} of {trim['key']}) from {trim['key']} "
                f"(D7 ROAS {trim['roas_d7_cur'] * 100:.1f}%) to {scale['key']} "
                f"({scale['roas_d7_cur'] * 100:.1f}%, blended {blended * 100:.1f}%): "
                f"~+{money(usd)}/wk of D7 revenue.")
        keys = [trim["key"], scale["key"]]
    elif trim:
        amt = trim["spend_cur"] * SHIFT_SHARE
        usd = amt * (blended - trim["roas_d7_cur"])
        text = (f"Trim {trim['key']} by ~{money(amt)}/wk: D7 ROAS {trim['roas_d7_cur'] * 100:.1f}% "
                f"vs {blended * 100:.1f}% blended (~+{money(usd)}/wk of D7 revenue if redeployed).")
        keys = [trim["key"]]
    elif scale:
        amt = scale["spend_cur"] * SHIFT_SHARE
        usd = amt * (scale["roas_d7_cur"] - blended)
        text = (f"Test +{SHIFT_SHARE:.0%} budget on {scale['key']}: D7 ROAS "
                f"{scale['roas_d7_cur'] * 100:.1f}% vs {blended * 100:.1f}% blended and improving, "
                f"CPI {fpct(scale['cpi_pct'])} (~+{money(usd)}/wk of D7 revenue).")
        keys = [scale["key"]]
    else:
        return None
    return {"usd": usd, "at_stake_usd": usd, "text": text, "source": "wow", "keys": keys}


def candidate_actions(wow: dict, struct: dict) -> list[dict]:
    """All candidate actions, ranked by the weekly D7 revenue at stake in the problem each one
    addresses (so the recommended action tackles the biggest-dollar issue first)."""
    cands = [a["action"] for a in struct["issues"]]
    w = wow_action(wow)
    if w:
        cands.append(w)
    return sorted(cands, key=lambda c: c["at_stake_usd"], reverse=True)


def pick_action(cands: list[dict], wow: dict, checks, warnings) -> str:
    failed = [c for c in checks if not c[1]]
    if failed:
        return (f"Hold budget changes: {len(failed)} validation check(s) failed "
                f"({failed[0][0]}). Fix the data before acting on this report.")
    if not cands:
        blended = wow[("total", "All paid")]["roas_d7_cur"]
        return (f"Hold budgets: no channel or country is far enough from the {blended * 100:.1f}% "
                f"blended D7 ROAS, persistently or this week, to justify a shift.")
    top = cands[0]
    names = set(top.get("keys") or ([top["key"]] if top.get("dim") == "channel" else []))
    flagged = sorted({w["date"] for w in warnings if w["channel"] in names and w["country"] == "all"})
    caveat = ""
    if flagged:
        ch = sorted({w["channel"] for w in warnings if w["channel"] in names and w["country"] == "all"})
        caveat = f" Also confirm the {'/'.join(ch)} day-level outlier(s) on {', '.join(flagged)} with the MMP."
    return top["text"] + caveat


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


def struct_windows(week_start: date, struct: dict, wow: dict) -> dict:
    t = wow[("total", "All paid")]
    weeks = struct["weeks"]
    recent = weeks[-RECENT_WEEKS:]
    d30_max = max((w["d30_max_install_date"] for w in struct.get("rows", [])
                   if w["dim"] == "total" and w["d30_max_install_date"]), default=None)
    return {
        "trailing": f"installs {weeks[0]} → {t['d7_max_install_date_cur']} ({len(weeks)} weeks, "
                    f"D7-mature cohorts only)",
        "now": f"installs {recent[0]} → {t['d7_max_install_date_cur']} (last {len(recent)} weeks)",
        "d30": (f"installs {weeks[0]} → {d30_max} (D30-mature cohorts only)" if d30_max else "none mature"),
    }


def wow_line(drivers: list[dict]) -> str:
    """The three WoW drivers compressed to one line for Slack."""
    out = []
    for d in drivers:
        e, imp, name = d["e"], d["impact_usd"], d["key"]
        if d["lens"] == "volume":
            out.append(f"{name} spend {signed_money(imp)} ({fpct(e['spend_pct'])})")
        elif d["lens"] == "efficiency":
            out.append(f"{name} CPI {fpct(e['cpi_pct'])} ({'+' if imp > 0 else '-'}{money(abs(imp))} cost)")
        else:
            out.append(f"{name} D7 ROAS {fpp(e['roas_d7_pp'])} ({signed_money(imp)} D7 rev)")
    return " · ".join(out)


def slack_text(week_start, wow, organic, drivers, action, checks, warnings, struct) -> str:
    w = windows(week_start, wow)
    failed = [c for c in checks if not c[1]]
    status = (f"{len(checks)}/{len(checks)} checks passed" if not failed
              else f":warning: {len(failed)} validation check(s) FAILED")
    if warnings:
        status += f", {len(warnings)} day-level outlier(s)"
    if struct["skipped"]:
        issues = ["• _Not enough history for the structural view._"]
    elif struct["issues"]:
        issues = [f"• :red_circle: {issue_text(a)}" for a in struct["issues"][:3]]
        if len(struct["issues"]) > 3:
            issues.append(f"• _+{len(struct['issues']) - 3} more in the full report._")
    else:
        issues = ["• None: no channel or country is persistently far below the rest of paid "
                  "or has stepped down."]
    sw = struct_windows(week_start, struct, wow) if not struct["skipped"] else {}
    lines = [
        f"*Dice Kingdom — Weekly UA* · {w['week']}",
        f":dart: {headline(wow, organic)}",
        "",
        f"*Structural issues* _(vs rest of paid and own last {len(struct['weeks'])} wks; "
        f"$ = D7 revenue at stake per week)_",
        *issues,
        "",
        f":point_right: *Action (largest $):* {action}",
        "",
        f"*WoW:* {wow_line(drivers)}",
        f"_Paid only. Spend/installs/CPI: activity {w['week']} vs prior week. D7: installs "
        f"{week_start} → {wow[('total', 'All paid')]['d7_max_install_date_cur'][5:]} vs prior week, "
        f"mature cohorts only."
        + (f" Structural: installs {struct['weeks'][0]} → "
           f"{wow[('total', 'All paid')]['d7_max_install_date_cur'][5:]}." if sw else "")
        + f" {status}._",
    ]
    return "\n".join(lines)


def structural_md(week_start, struct: dict, wow: dict, cands: list[dict]) -> list[str]:
    if struct["skipped"]:
        return ["## Structural issues", "", "Not enough weekly history for the structural view.", ""]
    sw = struct_windows(week_start, struct, wow)
    n = len(struct["weeks"])
    out = [
        "## Structural issues",
        "",
        f"Each channel and country vs the **rest of paid** (paid total minus itself) and vs its own "
        f"last {n} weeks. Windows: trailing {sw['trailing']}; \"now\" = {sw['now']}; "
        f"D30 confirmation {sw['d30']}. Flags (all need ≥ {money(MIN_IMPACT_USD)}/wk of D7 revenue at stake):",
        f"- **Persistent gap:** weekly D7 ROAS below {FAR_BELOW:.0%} of rest of paid in each of the last "
        f"≥ {PERSIST_WEEKS} weeks. $ = (rest ROAS − ROAS) × weekly spend, last {RECENT_WEEKS} weeks.",
        f"- **Step change:** D7 ROAS down ≥ {STEP_CHANGE:.0%} after a split week vs before it (≥ "
        f"{STEP_MIN_WEEKS} weeks each side, every week after below the earlier level). "
        f"$ = (ROAS before − after) × weekly spend after.",
        f"- **Budget drift:** spend share up ≥ {SHARE_DRIFT_PP:.0f}pp (last {RECENT_WEEKS} weeks vs "
        f"before) while D7 ROAS is below rest of paid. $ = extra weekly spend × ROAS gap.",
        "",
    ]
    if struct["issues"]:
        out += [f"{i}. {issue_text(a).replace('*', '**')}" for i, a in enumerate(struct["issues"], 1)]
    else:
        out.append("No structural issues flagged.")
    out += ["", "### Candidate actions, ranked by weekly D7 revenue impact", ""]
    out += ([f"{i}. {money(c['at_stake_usd'])}/wk at stake ({c['source']}): {c['text']}"
             for i, c in enumerate(cands, 1)] or ["- none"])
    out += ["", "_$ figures assume redeployed budget earns the rest-of-paid average D7 ROAS; marginal "
            "returns are usually lower, so treat them as directional._", "",
            f"### Channel and country vs rest of paid (last {RECENT_WEEKS} weeks)", "",
            "| | Share | Δpp vs before | D7 ROAS | Rest | Index | CPI | Rest | Index | D30 ROAS | Rest "
            "| Weeks <80% | Step | $/wk at stake |",
            "|---|" + "---:|" * 14]
    order = {("channel", k): i for i, k in enumerate(CHANNEL_ORDER)}
    order.update({("country", k): 10 + i for i, k in enumerate(COUNTRY_ORDER)})
    for a in sorted(struct["entities"], key=lambda a: order.get((a["dim"], a["key"]), 99)):
        now, rest = a["now"], a["rest_now"]
        st = a["step"]
        out.append(
            f"| {entity(a)} | {pct1(now['share'])} | {fpp(a['share_pp'])} | {pct1(now['roas7'])} | "
            f"{pct1(rest['roas7'])} | {a['roas_idx']:.2f} | ${now['cpi']:.2f} | ${rest['cpi']:.2f} | "
            f"{a['cpi_idx']:.2f} | {pct1(a['all']['roas30'])} | {pct1(a['rest_all']['roas30'])} | "
            f"{a['streak']} | {'w/c ' + st['week'] + ' ' + fpct(st['chg']) if st else '–'} | "
            f"{money(a['impact_usd']) if a['impact_usd'] else '–'} |")
    out += ["", f"### Weekly D7 ROAS, index vs rest of paid (week starting)", "",
            "| | " + " | ".join(w[5:] for w in struct["weeks"]) + " |",
            "|---|" + "---:|" * n]
    for a in sorted(struct["entities"], key=lambda a: order.get((a["dim"], a["key"]), 99)):
        cells = [f"{pct1(r)} ({ratio(r, rr):.2f})" if r is not None and rr else "n/a"
                 for r, rr in zip(a["weekly_roas7"], a["weekly_rest_roas7"])]
        out.append(f"| {entity(a)} | " + " | ".join(cells) + " |")
    out.append("")
    return out


def markdown_report(week_start, as_of, wow, organic, kpis, drivers, action, checks, warnings,
                    struct, cands) -> str:
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
        *([f"- Structural issues: {struct_windows(week_start, struct, wow)['trailing']}; D30 "
           f"confirmation {struct_windows(week_start, struct, wow)['d30']}"] if not struct["skipped"] else []),
        "",
        "## Summary",
        "",
        f"**{headline(wow, organic)}**",
        "",
        "Week-over-week drivers:",
        "",
        *[f"{i}. {driver_text(d).replace('*', '**')}" for i, d in enumerate(drivers, 1)],
        "",
        f"**Recommended action (largest weekly $ impact):** {action}",
        "",
        *structural_md(week_start, struct, wow, cands),
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
    weekly = run_sql(con, "structural_weekly.sql", params)
    con.close()

    checks, warnings = validate(delivery, quality, reconcile, nulls, outliers, organic, kpis,
                                weekly, week_start)
    wow = wow_table(delivery, quality)
    drivers = pick_drivers(wow)
    struct = structural_issues(weekly)
    cands = candidate_actions(wow, struct)
    action = pick_action(cands, wow, checks, warnings)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"weekly_ua_{week_start}"
    slack = slack_text(week_start, wow, organic, drivers, action, checks, warnings, struct)
    stem.with_suffix(".slack").write_text(slack + "\n")
    stem.with_suffix(".md").write_text(
        markdown_report(week_start, as_of, wow, organic, kpis, drivers, action, checks, warnings,
                        struct, cands))
    stem.with_suffix(".json").write_text(json.dumps({
        "week_start": week_start.isoformat(), "as_of": as_of.isoformat(),
        "windows": windows(week_start, wow),
        "checks": [{"check": n, "passed": ok, "detail": d} for n, ok, d in checks],
        "outliers": warnings,
        "wow": [v for v in wow.values()],
        "drivers": [{k: v for k, v in d.items() if k != "e"} for d in drivers],
        "action": action,
        "candidate_actions": cands,
        "structural": {
            "weeks": struct["weeks"],
            "windows": struct_windows(week_start, struct, wow) if not struct["skipped"] else None,
            "issues": [{"entity": entity(a), "impact_usd": a["impact_usd"], "text": issue_text(a)}
                       for a in struct["issues"]],
            "entities": struct["entities"],
        },
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

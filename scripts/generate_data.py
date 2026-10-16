"""Generate synthetic user-acquisition data for "Dice Kingdom".

Dice Kingdom is a fictional free-to-play casual mobile game. This script builds
data/marketing.duckdb with 90 days of paid + organic acquisition, cohort and
daily KPI data, then validates it.

Tables
------
ua_spend   (date, channel, campaign, country, platform, creative_id,
            spend, impressions, clicks, installs)
cohorts    (install_date, channel, campaign, country, platform, installs,
            d1_retained, d7_retained, d30_retained,
            revenue_d0, revenue_d7, revenue_d30, payers_d7)
daily_kpis (date, platform, dau, revenue, payers)

Cohort metrics that have not matured by the data snapshot date (the last day
of the window) are NULL, e.g. d30_retained for installs in the last 30 days.

Usage: python scripts/generate_data.py [--seed 20260916] [--out data/marketing.duckdb]
"""

from __future__ import annotations

import argparse
import math
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

START_DATE = date(2026, 6, 1)
N_DAYS = 90
END_DATE = START_DATE + timedelta(days=N_DAYS - 1)

PLATFORMS = ["iOS", "Android"]
PLATFORM_BUDGET_SHARE = {"iOS": 0.55, "Android": 0.45}
PLATFORM_CPI_MULT = {"iOS": 1.0, "Android": 0.72}
PLATFORM_RET_MULT = {"iOS": 1.05, "Android": 0.95}
PLATFORM_PAYER_MULT = {"iOS": 1.25, "Android": 0.80}

# country: base iOS CPI, budget share, D1/D7/D30 retention multiplier,
# D7 payer rate, D7 ARPPU (USD), D7 ad revenue per install (USD), organic/day
COUNTRIES = {
    "US": dict(cpi=3.10, share=0.36, ret=1.00, payer=0.031, arppu=12.5, ad=0.110, organic=1400),
    "UK": dict(cpi=2.45, share=0.10, ret=0.98, payer=0.027, arppu=10.8, ad=0.085, organic=380),
    "DE": dict(cpi=2.70, share=0.10, ret=1.02, payer=0.029, arppu=11.2, ad=0.080, organic=420),
    "JP": dict(cpi=3.60, share=0.14, ret=1.08, payer=0.036, arppu=15.0, ad=0.070, organic=520),
    "BR": dict(cpi=0.62, share=0.20, ret=0.90, payer=0.012, arppu=5.2, ad=0.022, organic=900),
    "FR": dict(cpi=2.25, share=0.10, ret=0.97, payer=0.025, arppu=10.1, ad=0.075, organic=330),
}

# channel: daily budget (USD), CPI multiplier, CTR, click->install CVR,
# retention / payer quality multipliers
CHANNELS = {
    "Meta":     dict(budget=16000, cpi=1.00, ctr=0.0120, cvr=0.30, ret=1.00, pay=1.00),
    "Google":   dict(budget=12000, cpi=1.08, ctr=0.0350, cvr=0.22, ret=0.97, pay=1.05),
    "AppLovin": dict(budget=10500, cpi=0.92, ctr=0.0180, cvr=0.38, ret=1.05, pay=1.12),
    "Unity":    dict(budget=5000, cpi=0.82, ctr=0.0160, cvr=0.34, ret=0.90, pay=0.85),
    "TikTok":   dict(budget=7000, cpi=0.78, ctr=0.0095, cvr=0.26, ret=0.86, pay=0.80),
}
ORGANIC = dict(ret=1.12, pay=1.30)

# Two campaigns per paid channel, three creatives per campaign.
# creative: (creative_id, CTR multiplier, baseline spend weight)
CAMPAIGNS = {
    "Meta": {
        "meta_aeo_purchase_t1": [("META-AEO-01", 1.05, 1.0), ("META-AEO-02", 0.95, 0.8), ("META-AEO-03", 1.00, 0.9)],
        "meta_broad_installs": [("META-BRD-01", 1.10, 1.2), ("META-BRD-02", 0.90, 0.7), ("META-BRD-03", 1.00, 1.0)],
    },
    "Google": {
        "uac_installs_global": [("GGL-UAC-01", 1.00, 1.0), ("GGL-UAC-02", 1.05, 1.1), ("GGL-UAC-03", 0.92, 0.7)],
        "uac_tcpa_payers": [("GGL-TCPA-01", 1.00, 1.0), ("GGL-TCPA-02", 0.97, 0.9), ("GGL-TCPA-03", 1.04, 1.0)],
    },
    "AppLovin": {
        "applovin_roas_d7": [("APL-ROAS-01", 1.02, 1.0), ("APL-ROAS-02", 0.98, 1.0), ("APL-ROAS-03", 1.00, 0.8)],
        "applovin_cpi_scale": [("APL-CPI-01", 1.06, 1.1), ("APL-CPI-02", 0.94, 0.8), ("APL-CPI-03", 1.00, 1.0)],
    },
    "Unity": {
        "unity_playable_installs": [("UNT-PLY-01", 1.08, 1.1), ("UNT-PLY-02", 0.95, 0.9), ("UNT-PLY-03", 0.97, 0.9)],
        "unity_video_retarget": [("UNT-VID-01", 1.00, 1.0), ("UNT-VID-02", 1.03, 1.0), ("UNT-VID-03", 0.96, 0.8)],
    },
    "TikTok": {
        "tiktok_spark_ugc": [("TT-UGC-01", 1.00, 0.8), ("TT-UGC-02", 1.05, 1.1), ("TT-UGC-03", 0.95, 0.7)],
        "tiktok_value_bidding": [("TT-VAL-01", 1.00, 1.0), ("TT-VAL-02", 1.02, 1.0), ("TT-VAL-03", 0.97, 0.9)],
    },
}

# Base retention / revenue shape (US iOS, quality 1.0)
BASE_D1, BASE_D7, BASE_D30 = 0.40, 0.155, 0.058
D0_SHARE_OF_D7 = 0.34  # revenue_d0 / revenue_d7
D30_OVER_D7 = 2.25  # revenue_d30 / revenue_d7

# --- Scenario parameters -----------------------------------------------------
# Attribution outage: one channel/platform stops reporting most installs for a few
# days; the unattributed installs fall into Organic instead.
OUTAGE_CHANNEL = "Google"
OUTAGE_PLATFORM = "Android"
OUTAGE_START_DAY = 66
OUTAGE_DAYS = 4
OUTAGE_CAPTURE = 0.06  # share of installs still attributed during the outage

# Product regression: cohorts on one platform retain worse after an app release.
REGRESSION_PLATFORM = "Android"
REGRESSION_START_DAY = 51
REGRESSION_RET_MULT = {"d1": 0.82, "d7": 0.68, "d30": 0.62}

# Invalid traffic: one campaign starts buying click-spam installs that never play.
FRAUD_CAMPAIGN = "unity_video_retarget"
FRAUD_START_DAY = 38
FRAUD_RAMP = 5
FRAUD_INSTALL_MULT = 1.30  # extra fraudulent installs per genuine install at full ramp
FRAUD_CLICK_MULT = 9.0  # fraudulent clicks per fraudulent install
FRAUD_D1 = 0.015
# -----------------------------------------------------------------------------


def day_factor(d: date, rng: np.random.Generator) -> float:
    """Weekday seasonality plus a mild upward trend and noise."""
    weekday = {0: 0.96, 1: 0.95, 2: 0.97, 3: 0.99, 4: 1.03, 5: 1.08, 6: 1.06}[d.weekday()]
    trend = 1.0 + 0.10 * ((d - START_DATE).days / N_DAYS)
    return weekday * trend * rng.normal(1.0, 0.04)


def outage_capture(channel: str, platform: str, day_idx: int) -> float:
    if (channel == OUTAGE_CHANNEL and platform == OUTAGE_PLATFORM
            and OUTAGE_START_DAY <= day_idx < OUTAGE_START_DAY + OUTAGE_DAYS):
        return OUTAGE_CAPTURE
    return 1.0


def fraud_multiplier(campaign: str, day_idx: int) -> float:
    if campaign != FRAUD_CAMPAIGN or day_idx < FRAUD_START_DAY:
        return 0.0
    ramp = min(1.0, (day_idx - FRAUD_START_DAY + 1) / FRAUD_RAMP)
    return FRAUD_INSTALL_MULT * ramp


def build_ua_spend(rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    rows = []
    fraud: dict[tuple, int] = {}
    for day_idx in range(N_DAYS):
        d = START_DATE + timedelta(days=day_idx)
        shares = {c: p["share"] for c, p in COUNTRIES.items()}
        unattributed_cp: dict[tuple[str, str], int] = {}
        paid_installs_cp: dict[tuple[str, str], int] = {}
        for channel, ch in CHANNELS.items():
            ch_budget = ch["budget"] * day_factor(d, rng)
            camp_items = list(CAMPAIGNS[channel].items())
            camp_weights = rng.dirichlet([40] * len(camp_items))
            for (campaign, creatives), camp_w in zip(camp_items, camp_weights):
                cw = np.array([w for _, _, w in creatives]) * rng.normal(1.0, 0.06, len(creatives))
                cw = np.clip(cw, 0.05, None)
                cw /= cw.sum()
                for (creative_id, ctr_m, _), cr_w in zip(creatives, cw):
                    for country, cp in COUNTRIES.items():
                        for platform in PLATFORMS:
                            spend = (ch_budget * camp_w * cr_w * shares[country]
                                     * PLATFORM_BUDGET_SHARE[platform] * rng.lognormal(0, 0.10))
                            target_cpi = cp["cpi"] * ch["cpi"] * PLATFORM_CPI_MULT[platform]
                            ctr = ch["ctr"] * ctr_m
                            # CPM is set so that a creative with average CTR hits the target CPI
                            cpm = target_cpi * 1000 * ch["ctr"] * ch["cvr"]
                            cpm *= rng.lognormal(0, 0.05)
                            impressions = int(rng.poisson(spend / cpm * 1000))
                            ctr_eff = ctr * rng.lognormal(0, 0.05)
                            clicks = int(rng.binomial(impressions, min(ctr_eff, 0.5)))
                            cvr = min(ch["cvr"] * rng.lognormal(0, 0.05), 0.95)
                            installs = int(rng.binomial(clicks, cvr))
                            capture = outage_capture(channel, platform, day_idx)
                            if capture < 1.0:
                                kept = int(rng.binomial(installs, capture))
                                unattributed_cp[(country, platform)] = (
                                    unattributed_cp.get((country, platform), 0) + installs - kept)
                                installs = kept
                            fm = fraud_multiplier(campaign, day_idx)
                            if fm:
                                fake = int(rng.poisson(installs * fm))
                                fake_clicks = int(rng.poisson(fake * FRAUD_CLICK_MULT))
                                fake_clicks = max(fake_clicks, fake)
                                clicks += fake_clicks
                                impressions = max(impressions, clicks)
                                installs += fake
                                fk = (d, channel, campaign, country, platform)
                                fraud[fk] = fraud.get(fk, 0) + fake
                            rows.append((d, channel, campaign, country, platform, creative_id,
                                         round(spend, 2), impressions, clicks, installs))
                            key = (country, platform)
                            paid_installs_cp[key] = paid_installs_cp.get(key, 0) + installs
        # Organic: country baseline plus a small halo from paid activity
        for country, cp in COUNTRIES.items():
            for platform in PLATFORMS:
                base = cp["organic"] * (0.45 if platform == "iOS" else 0.55)
                halo = 0.08 * paid_installs_cp[(country, platform)]
                lam = (base + halo) * day_factor(d, rng)
                installs = int(rng.poisson(max(lam, 0))) + unattributed_cp.get((country, platform), 0)
                rows.append((d, "Organic", "organic", country, platform, "organic",
                             0.0, 0, 0, installs))
    ua = pd.DataFrame(rows, columns=["date", "channel", "campaign", "country", "platform",
                                     "creative_id", "spend", "impressions", "clicks", "installs"])
    return ua, fraud


def build_cohorts(ua: pd.DataFrame, fraud: dict, rng: np.random.Generator) -> pd.DataFrame:
    keys = ["date", "channel", "campaign", "country", "platform"]
    agg = ua.groupby(keys, as_index=False)["installs"].sum().rename(columns={"date": "install_date"})

    rows = []
    for r in agg.itertuples(index=False):
        n_total = int(r.installs)
        n_fake = fraud.get((r.install_date, r.channel, r.campaign, r.country, r.platform), 0)
        n = n_total - n_fake
        cp = COUNTRIES[r.country]
        q = ORGANIC if r.channel == "Organic" else CHANNELS[r.channel]
        ret_m = cp["ret"] * q["ret"] * PLATFORM_RET_MULT[r.platform] * rng.lognormal(0, 0.03)
        p1 = min(BASE_D1 * ret_m, 0.9)
        p7 = min(BASE_D7 * ret_m, p1)
        p30 = min(BASE_D30 * ret_m, p7)
        day_idx = (r.install_date - START_DATE).days
        if r.platform == REGRESSION_PLATFORM and day_idx >= REGRESSION_START_DAY:
            p1 *= REGRESSION_RET_MULT["d1"]
            p7 = min(p7 * REGRESSION_RET_MULT["d7"], p1)
            p30 = min(p30 * REGRESSION_RET_MULT["d30"], p7)
        d1 = int(rng.binomial(n, p1))
        d7 = int(rng.binomial(d1, p7 / p1)) if d1 else 0
        d30 = int(rng.binomial(d7, p30 / p7)) if d7 else 0
        if n_fake:
            f1 = int(rng.binomial(n_fake, FRAUD_D1))
            f7 = int(rng.binomial(f1, 0.15)) if f1 else 0
            d1, d7, d30 = d1 + f1, d7 + f7, d30

        payer_rate = cp["payer"] * q["pay"] * PLATFORM_PAYER_MULT[r.platform]
        arppu = cp["arppu"] * (1.15 if r.platform == "iOS" else 0.90)
        ad_arpu = cp["ad"] * (0.85 if r.platform == "iOS" else 1.15)
        payers = int(rng.binomial(n, min(payer_rate, 1.0)))
        iap = sum(rng.gamma(2.0, arppu / 2.0, payers)) if payers else 0.0
        ads = n * ad_arpu * rng.lognormal(0, 0.08)
        rev7 = iap + ads
        rev0 = rev7 * D0_SHARE_OF_D7 * rng.lognormal(0, 0.06)
        rev0 = min(rev0, rev7)
        rev30 = rev7 * D30_OVER_D7 * rng.lognormal(0, 0.06)
        rev30 = max(rev30, rev7)

        age = (END_DATE - r.install_date).days
        rows.append((
            r.install_date, r.channel, r.campaign, r.country, r.platform, n_total,
            d1 if age >= 1 else None,
            d7 if age >= 7 else None,
            d30 if age >= 30 else None,
            round(rev0, 2),
            round(rev7, 2) if age >= 7 else None,
            round(rev30, 2) if age >= 30 else None,
            payers if age >= 7 else None,
        ))
    df = pd.DataFrame(rows, columns=[
        "install_date", "channel", "campaign", "country", "platform", "installs",
        "d1_retained", "d7_retained", "d30_retained",
        "revenue_d0", "revenue_d7", "revenue_d30", "payers_d7"])
    for c in ["d1_retained", "d7_retained", "d30_retained", "payers_d7"]:
        df[c] = df[c].astype("Int64")
    return df


def build_daily_kpis(ua: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """DAU from a legacy user base plus new installs decayed by a power-law curve."""
    b = math.log(BASE_D1 / BASE_D30) / math.log(30)
    curve = np.array([1.0] + [BASE_D1 * k ** (-b) for k in range(1, N_DAYS)])
    legacy = {"iOS": 640_000, "Android": 820_000}
    arpdau = {"iOS": 0.235, "Android": 0.118}
    payer_share = {"iOS": 0.021, "Android": 0.013}

    rows = []
    for platform in PLATFORMS:
        daily = (ua[ua.platform == platform].groupby("date")["installs"].sum()
                 .reindex([START_DATE + timedelta(days=i) for i in range(N_DAYS)], fill_value=0)
                 .to_numpy())
        if platform == REGRESSION_PLATFORM:
            daily = daily * np.where(np.arange(N_DAYS) >= REGRESSION_START_DAY, REGRESSION_RET_MULT["d7"], 1.0)
        new_users = np.convolve(daily, curve)[:N_DAYS]
        for i in range(N_DAYS):
            d = START_DATE + timedelta(days=i)
            weekend = 1.07 if d.weekday() >= 5 else 1.0
            dau = int((legacy[platform] * 0.9955 ** i + new_users[i]) * weekend * rng.normal(1.0, 0.015))
            payers = int(rng.binomial(dau, payer_share[platform] * rng.normal(1.0, 0.04)))
            revenue = dau * arpdau[platform] * weekend * rng.lognormal(0, 0.05)
            rows.append((d, platform, dau, round(revenue, 2), payers))
    return pd.DataFrame(rows, columns=["date", "platform", "dau", "revenue", "payers"])


def write_db(path: Path, ua: pd.DataFrame, cohorts: pd.DataFrame, kpis: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = duckdb.connect(str(path))
    con.execute("""
        CREATE TABLE ua_spend (
            date DATE, channel VARCHAR, campaign VARCHAR, country VARCHAR, platform VARCHAR,
            creative_id VARCHAR, spend DECIMAL(12,2), impressions BIGINT, clicks BIGINT,
            installs BIGINT)""")
    con.execute("""
        CREATE TABLE cohorts (
            install_date DATE, channel VARCHAR, campaign VARCHAR, country VARCHAR,
            platform VARCHAR, installs BIGINT, d1_retained BIGINT, d7_retained BIGINT,
            d30_retained BIGINT, revenue_d0 DECIMAL(12,2), revenue_d7 DECIMAL(12,2),
            revenue_d30 DECIMAL(12,2), payers_d7 BIGINT)""")
    con.execute("""
        CREATE TABLE daily_kpis (
            date DATE, platform VARCHAR, dau BIGINT, revenue DECIMAL(12,2), payers BIGINT)""")
    for name, df in [("ua_spend", ua), ("cohorts", cohorts), ("daily_kpis", kpis)]:
        con.register("df_view", df)
        con.execute(f"INSERT INTO {name} SELECT * FROM df_view")
        con.unregister("df_view")
    con.close()


def validate(path: Path) -> None:
    con = duckdb.connect(str(path), read_only=True)
    checks = {
        "ua_spend: no negative values":
            "SELECT count(*) FROM ua_spend WHERE spend < 0 OR impressions < 0 OR clicks < 0 OR installs < 0",
        "ua_spend: installs <= clicks <= impressions (paid)":
            "SELECT count(*) FROM ua_spend WHERE channel <> 'Organic' AND (installs > clicks OR clicks > impressions)",
        "ua_spend: organic has zero spend":
            "SELECT count(*) FROM ua_spend WHERE channel = 'Organic' AND spend <> 0",
        "cohorts: no negative values":
            """SELECT count(*) FROM cohorts WHERE installs < 0 OR d1_retained < 0 OR d7_retained < 0
               OR d30_retained < 0 OR revenue_d0 < 0 OR revenue_d7 < 0 OR revenue_d30 < 0 OR payers_d7 < 0""",
        "cohorts: retention monotone (installs >= d1 >= d7 >= d30)":
            """SELECT count(*) FROM cohorts WHERE d1_retained > installs OR d7_retained > d1_retained
               OR d30_retained > d7_retained""",
        "cohorts: revenue monotone (d0 <= d7 <= d30)":
            "SELECT count(*) FROM cohorts WHERE revenue_d0 > revenue_d7 OR revenue_d7 > revenue_d30",
        "cohorts: payers_d7 <= installs":
            "SELECT count(*) FROM cohorts WHERE payers_d7 > installs",
        "daily_kpis: no negative values":
            "SELECT count(*) FROM daily_kpis WHERE dau < 0 OR revenue < 0 OR payers < 0",
        "cohorts installs == ua_spend installs per day/channel":
            """WITH u AS (SELECT date, channel, sum(installs) i FROM ua_spend GROUP BY ALL),
                    c AS (SELECT install_date AS date, channel, sum(installs) i FROM cohorts GROUP BY ALL)
               SELECT count(*) FROM u FULL OUTER JOIN c USING (date, channel)
               WHERE u.i IS DISTINCT FROM c.i""",
        "cohorts installs == ua_spend installs per day/channel/campaign/country/platform":
            """WITH u AS (SELECT date, channel, campaign, country, platform, sum(installs) i
                          FROM ua_spend GROUP BY ALL),
                    c AS (SELECT install_date AS date, channel, campaign, country, platform, installs i
                          FROM cohorts)
               SELECT count(*) FROM u FULL OUTER JOIN c USING (date, channel, campaign, country, platform)
               WHERE u.i IS DISTINCT FROM c.i""",
    }
    failed = []
    print("\nValidation")
    for name, sql in checks.items():
        bad = con.execute(sql).fetchone()[0]
        print(f"  [{'PASS' if bad == 0 else 'FAIL'}] {name} (violations: {bad})")
        if bad:
            failed.append(name)

    print("\nRow counts")
    for t in ["ua_spend", "cohorts", "daily_kpis"]:
        print(f"  {t:<11} {con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:>8,}")
    lo, hi = con.execute("SELECT min(date), max(date) FROM ua_spend").fetchone()
    spend, installs = con.execute("SELECT sum(spend), sum(installs) FROM ua_spend").fetchone()
    print(f"\n  Date range: {lo} -> {hi}")
    print(f"  Total spend: ${spend:,.0f} | total installs: {installs:,}")
    con.close()
    if failed:
        raise SystemExit(f"Validation failed: {failed}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=20260916)
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parent.parent / "data" / "marketing.duckdb")
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    ua, fraud = build_ua_spend(rng)
    cohorts = build_cohorts(ua, fraud, rng)
    kpis = build_daily_kpis(ua, rng)
    write_db(args.out, ua, cohorts, kpis)
    print(f"Wrote {args.out}")
    validate(args.out)


if __name__ == "__main__":
    main()

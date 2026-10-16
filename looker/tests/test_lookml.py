"""LookML checks: syntax (lkml parser), house rules from CLAUDE.md, and SQL logic against DuckDB.

    python -m unittest discover -s looker/tests -v      (or: pytest looker/tests)
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

import lkml
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lookml_sql import LOOKER_DIR, Renderer, load_model, load_views  # noqa: E402

REPO = LOOKER_DIR.parent
DB = REPO / "data" / "marketing.duckdb"
COHORT_KEYS = ["install_raw", "channel", "campaign", "country", "platform"]


class TestSyntax(unittest.TestCase):
    def test_lkml_files_parse(self):
        files = sorted(LOOKER_DIR.glob("**/*.lkml"))
        self.assertEqual(len(files), 5)
        for path in files:
            with self.subTest(path=path.name):
                self.assertTrue(lkml.load(path.read_text()))

    def test_dashboard_parses(self):
        dash = yaml.safe_load((LOOKER_DIR / "dashboards" / "weekly_ua.dashboard.lookml").read_text())
        self.assertEqual(dash[0]["dashboard"], "weekly_ua")

    def test_model(self):
        model = load_model()
        self.assertEqual(model["connection"], "redshift_marketing")
        self.assertEqual({e["name"] for e in model["explores"]}, {"ua_performance", "ua_spend", "daily_kpis"})

    def test_source_tables_in_marketing_schema(self):
        views = load_views()
        for name in ("ua_spend", "cohorts", "daily_kpis"):
            self.assertEqual(views[name]["sql_table_name"].strip(), f"marketing.{name}")
        self.assertIn("FROM marketing.ua_spend", views["spend_cohort_grain"]["derived_table"]["sql"])


class TestHouseRules(unittest.TestCase):
    views = load_views()

    def measures(self):
        for vname, view in self.views.items():
            for m in view.get("measures", []):
                yield vname, m

    def test_every_measure_has_label_and_description(self):
        for vname, m in self.measures():
            with self.subTest(measure=f"{vname}.{m['name']}"):
                self.assertTrue(m.get("label", "").strip())
                self.assertGreater(len(m.get("description", "").strip()), 20)

    def test_every_division_uses_nullif(self):
        for vname, m in self.measures():
            if "/" in m.get("sql", ""):
                with self.subTest(measure=f"{vname}.{m['name']}"):
                    self.assertRegex(m["sql"], r"/\s*NULLIF\(")
                    self.assertRegex(m["sql"], r"\* 10*\.0 /")  # avoid integer division

    def test_ratios_are_sums_not_averages(self):
        for vname, m in self.measures():
            self.assertNotIn(m["type"], ("average", "average_distinct"), f"{vname}.{m['name']}")

    def test_paid_measures_exclude_organic(self):
        r = Renderer(self.views)
        paid = {"ua_spend": ["spend", "impressions", "clicks", "paid_installs", "cpi", "ctr", "ipm"],
                "spend_cohort_grain": ["spend", "paid_installs", "cpi"],
                "cohorts": ["paid_revenue_d7", "spend_d7_mature", "roas_d7",
                            "paid_revenue_d30", "spend_d30_mature", "roas_d30"]}
        for vname, names in paid.items():
            for name in names:
                with self.subTest(measure=f"{vname}.{name}"):
                    sql = r.measure(vname, name)
                    sums = re.findall(r"SUM\((.*?) THEN ", sql)
                    self.assertEqual(len(sums), sql.count("SUM("), "every SUM must be filtered")
                    self.assertTrue(all("<> 'Organic'" in s for s in sums), sql)

    def test_dn_ratios_use_mature_cohorts_on_both_sides(self):
        r = Renderer(self.views)
        for name, column in [("d1_retention", "d1_retained"), ("d7_retention", "d7_retained"),
                             ("d30_retention", "d30_retained"), ("payer_conversion_d7", "payers_d7"),
                             ("roas_d7", "revenue_d7"), ("roas_d30", "revenue_d30")]:
            with self.subTest(measure=name):
                sql = r.measure("cohorts", name)
                conds = re.findall(r"SUM\(CASE WHEN (.*?) THEN ", sql)
                self.assertEqual(len(conds), 2, sql)                 # numerator and denominator
                self.assertEqual(conds[0], conds[1], "numerator and denominator filters differ")
                self.assertIn(f"cohorts.{column} IS NOT NULL", conds[0])


class TestFanOut(unittest.TestCase):
    def test_spend_derived_table_is_cohort_grain(self):
        sql = load_views()["spend_cohort_grain"]["derived_table"]["sql"]
        self.assertNotIn("creative_id", sql)
        self.assertRegex(sql, r"GROUP BY 1, 2, 3, 4, 5\b")

    def test_ua_performance_join(self):
        e = next(x for x in load_model()["explores"] if x["name"] == "ua_performance")
        self.assertEqual(e["from"], "cohorts")
        (join,) = e["joins"]
        self.assertEqual(join["name"], "spend_cohort_grain")
        self.assertEqual(join["relationship"], "one_to_one")
        for key in COHORT_KEYS:
            self.assertIn(f"${{cohorts.{key}}} = ${{spend_cohort_grain.{key}}}", join["sql_on"])


class TestDashboard(unittest.TestCase):
    def test_dashboard_fields_exist(self):
        r = Renderer()
        dash = yaml.safe_load((LOOKER_DIR / "dashboards" / "weekly_ua.dashboard.lookml").read_text())[0]
        refs = [f["field"] for f in dash["filters"]]
        for el in dash["elements"]:
            self.assertEqual((el["model"], el["explore"]), ("marketing", "ua_performance"))
            refs += el["fields"] + list(el.get("filters", {})) + list(el.get("listen", {}).values())
        for ref in refs:
            view, name = ref.split(".")
            with self.subTest(field=ref):
                self.assertIn(view, ("cohorts", "spend_cohort_grain"))
                self.assertIn(name, r.fields[view])

    def test_required_tiles(self):
        dash = yaml.safe_load((LOOKER_DIR / "dashboards" / "weekly_ua.dashboard.lookml").read_text())[0]
        fields = {el["name"]: el["fields"] for el in dash["elements"]}
        self.assertEqual(fields["kpi_spend"], ["spend_cohort_grain.spend"])
        self.assertEqual(fields["kpi_installs"], ["spend_cohort_grain.paid_installs"])
        self.assertEqual(fields["kpi_cpi"], ["spend_cohort_grain.cpi"])
        self.assertEqual(fields["kpi_roas_d7"], ["cohorts.roas_d7"])
        self.assertIn("cohorts.install_week", fields["weekly_spend_trend"])
        self.assertIn("cohorts.channel", fields["roas_d7_by_channel"])
        self.assertIn("cohorts.country", fields["roas_d7_by_country"])


@unittest.skipUnless(DB.exists(), "data/marketing.duckdb not built (python scripts/generate_data.py)")
class TestSqlLogic(unittest.TestCase):
    """Rendered LookML vs DuckDB (read-only), with data/marketing.duckdb attached as `marketing`."""

    @classmethod
    def setUpClass(cls):
        from check_sql_logic import compare, connect, explore
        cls.compare, cls.con, cls.r = staticmethod(compare), connect(), Renderer()
        cls.perf = explore("ua_performance")

    def test_join_has_no_fan_out_and_reconciles(self):
        n_cohorts, inst = self.con.execute("SELECT COUNT(*), SUM(installs) FROM cohorts").fetchone()
        base = self.r.query(self.perf, [], []).replace("SELECT\n  ", "SELECT COUNT(*) AS n, "
                                                       "SUM(cohorts.installs) AS i, "
                                                       "COUNT(spend_cohort_grain.install_date) AS matched, "
                                                       "SUM(spend_cohort_grain.installs) AS j ", 1)
        n, i, matched, j = self.con.execute(base).fetchone()
        self.assertEqual(n, n_cohorts)        # one_to_one: join adds no rows
        self.assertEqual(matched, n_cohorts)  # every cohort finds its spend row
        self.assertEqual(i, inst)
        self.assertEqual(j, inst)             # ua_spend installs at cohort grain == cohorts.installs

    def test_spend_survives_join(self):
        paid = self.con.execute("SELECT SUM(spend) FROM ua_spend WHERE channel <> 'Organic'").fetchone()[0]
        (spend,) = self.con.execute(self.r.query(self.perf, [], ["spend_cohort_grain.spend"])).fetchone()
        self.assertEqual(spend, paid)

    def test_cpi_and_roas_d7_match_weekly_report_2026_08_10(self):
        rows = self.compare("2026-08-10")
        self.assertEqual(len({r[0] for r in rows}), 6)
        for ch, metric, lookml_value, report_value, ok in rows:
            with self.subTest(channel=ch, metric=metric):
                self.assertTrue(ok, f"lookml={lookml_value} report={report_value}")


if __name__ == "__main__":
    unittest.main()

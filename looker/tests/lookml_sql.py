"""Tiny LookML -> SQL renderer, just enough to run this project's measures against DuckDB.

Looker itself is not available in CI, so this expands `${TABLE}`, `${field}` and `${view.field}`
references the way Looker does for the field types used in this project:
  - dimensions / dimension_groups (raw, date, week, month timeframes)
  - measures of type sum (with yes/no filters) and type number
It does not emulate symmetric aggregates: it is only used on one_to_one joins, where none apply.
"""
from __future__ import annotations

import re
from pathlib import Path

import lkml

LOOKER_DIR = Path(__file__).resolve().parents[1]
REF = re.compile(r"\$\{([^}]+)\}")
TIMEFRAMES = {
    "raw": "{}",
    "date": "{}",
    "week": "DATE_TRUNC('week', {})",   # week_start_day: monday (Redshift and DuckDB default)
    "month": "DATE_TRUNC('month', {})",
}


def load_model(name: str = "marketing") -> dict:
    return lkml.load((LOOKER_DIR / f"{name}.model.lkml").read_text())


def load_views() -> dict[str, dict]:
    views = {}
    for path in sorted((LOOKER_DIR / "views").glob("*.view.lkml")):
        for view in lkml.load(path.read_text())["views"]:
            views[view["name"]] = view
    return views


class Renderer:
    def __init__(self, views: dict[str, dict] | None = None):
        self.views = views or load_views()
        self.fields: dict[str, dict[str, tuple[str, dict]]] = {}
        for vname, view in self.views.items():
            f = {}
            for d in view.get("dimensions", []):
                f[d["name"]] = ("dimension", d)
            for g in view.get("dimension_groups", []):
                for tf in g.get("timeframes", []):
                    f[f"{g['name']}_{tf}"] = ("dimension", {**g, "sql": TIMEFRAMES[tf].format(g["sql"])})
            for m in view.get("measures", []):
                f[m["name"]] = ("measure", m)
            self.fields[vname] = f

    # -- references -------------------------------------------------------------------------
    def resolve(self, sql: str, view: str) -> str:
        def sub(match: re.Match) -> str:
            ref = match.group(1).strip()
            if ref == "TABLE":
                return view
            v, _, name = ref.rpartition(".")
            return self.field(v or view, name)
        return REF.sub(sub, sql).strip()

    def field(self, view: str, name: str) -> str:
        kind, f = self.fields[view][name]
        if kind == "dimension":
            return f"({self.resolve(f['sql'], view)})"
        return f"({self.measure(view, name)})"

    def measure(self, view: str, name: str) -> str:
        _, m = self.fields[view][name]
        if m["type"] == "number":
            return self.resolve(m["sql"], view)
        if m["type"] != "sum":
            raise NotImplementedError(f"measure type {m['type']} ({view}.{name})")
        expr = self.resolve(m["sql"], view)
        conds = [self.filter_condition(view, k, v) for k, v in self.filters(m)]
        if conds:
            expr = f"CASE WHEN {' AND '.join(conds)} THEN {expr} END"
        return f"SUM({expr})"

    @staticmethod
    def filters(m: dict) -> list[tuple[str, str]]:
        return [(k, v) for group in m.get("filters__all", []) for d in group for k, v in d.items()]

    def filter_condition(self, view: str, dim: str, value: str) -> str:
        sql = self.field(view, dim)
        if self.fields[view][dim][1].get("type") != "yesno" or value not in ("yes", "no"):
            raise NotImplementedError(f"filter {dim}: {value!r}")
        return sql if value == "yes" else f"NOT {sql}"

    # -- tables / explores ------------------------------------------------------------------
    def from_clause(self, view: str) -> str:
        v = self.views[view]
        if "sql_table_name" in v:
            return f"{v['sql_table_name'].strip()} AS {view}"
        return f"({v['derived_table']['sql'].strip()}) AS {view}"

    def query(self, explore: dict, dimensions: list[str], measures: list[str], where: str | None = None) -> str:
        """Render an explore query. Fields are 'view.field'; `where` may use ${view.field} refs."""
        base = explore.get("view_name", explore["name"])
        base_table = explore.get("from", base)
        if base_table != base:
            raise NotImplementedError("explore alias different from its view")
        joins = "".join(
            f"\n{j.get('type', 'left_outer').upper().replace('_', ' ')} JOIN {self.from_clause(j['name'])}"
            f"\n  ON {self.resolve(j['sql_on'], base)}"
            for j in explore.get("joins", [])
        )
        cols = [f"{self.field(*f.split('.'))} AS \"{f}\"" for f in dimensions]
        cols += [f"{self.measure(*f.split('.'))} AS \"{f}\"" for f in measures]
        sql = f"SELECT\n  " + ",\n  ".join(cols) + f"\nFROM {self.from_clause(base)}{joins}"
        if where:
            sql += f"\nWHERE {self.resolve(where, base)}"
        if dimensions:
            sql += "\nGROUP BY " + ", ".join(str(i + 1) for i in range(len(dimensions)))
            sql += "\nORDER BY 1"
        return sql

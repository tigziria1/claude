"""Agent 4 - Dashboard + Report Generator.

For every analysed dataset it writes to ``REPORTS_PATH``:

* ``<date>_<name>_dashboard.html`` - interactive dashboard: KPI cards, monthly
  trend, breakdown charts with hover tooltips, insights, and a searchable /
  filterable table of the cleaned data.
* ``<date>_<name>_report.html`` - printable report (executive summary, key
  figures, charts, Claude's insights, recommendations, data quality,
  signature + date). "Print / Save as PDF" in the browser produces the PDF.
* ``<date>_<name>_insights.json`` - the statistics and insights, for reuse.

The cleaned CSV export is written by the Data Cleaner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import PROJECT_ROOT, Settings
from agents.cleaner import FLAG_COLUMN
from agents.common import AnalysisResult, CleanedDataset, write_json

logger = logging.getLogger("agent.report")

TEMPLATES_DIR = PROJECT_ROOT / "templates"
MAX_TABLE_ROWS = 2000
MAX_CHART_CATEGORIES = 8
MAX_FILTERS = 3
CURRENCY_SYMBOLS: dict[str, str] = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥"}


@dataclass
class GeneratedReport:
    """Paths of the files written for one dataset."""

    name: str
    dashboard: Path | None
    report: Path | None
    insights: Path


def humanize(column: str | None) -> str:
    """``unitPrice`` -> ``Unit price``."""
    if not column:
        return ""
    words: list[str] = []
    current = ""
    for char in column:
        if char.isupper() and current:
            words.append(current)
            current = char
        else:
            current += char
    words.append(current)
    text = " ".join(w.lower() for w in words)
    return text[:1].upper() + text[1:]


def format_money(value: float | None, currency: str | None) -> str:
    """Format an amount with its currency symbol (``€1,081,244``)."""
    if value is None or pd.isna(value):
        return "–"
    digits = 0 if abs(value) >= 100 else 2
    number = f"{abs(value):,.{digits}f}"
    sign = "-" if value < 0 else ""
    if not currency:
        return f"{sign}{number}"
    symbol = CURRENCY_SYMBOLS.get(currency)
    return f"{sign}{symbol}{number}" if symbol else f"{sign}{number} {currency}"


def format_pct(value: float | None, signed: bool = True) -> str:
    """Format a percentage (``+12.3%``)."""
    if value is None or pd.isna(value):
        return "–"
    return f"{value:+.1f}%" if signed else f"{value:.1f}%"


def _delta_class(value: float | None) -> str:
    if value is None or pd.isna(value):
        return ""
    return "delta-up" if value >= 0 else "delta-down"


def build_kpis(analysis: AnalysisResult, currency: str | None) -> list[dict[str, str]]:
    """Build the stat cards shown at the top of the dashboard and report."""
    stats = analysis.stats
    kpis = stats["kpis"]
    amount = stats.get("primary_amount_column")
    ts = stats.get("time_series") or {}
    dq = stats["data_quality"]
    cards: list[dict[str, str]] = []
    if amount:
        cards.append({"label": f"Total {humanize(amount).lower()}", "value": format_money(kpis.get("total"), currency),
                      "sub": f"{ts['start']} → {ts['end']}" if ts else "", "delta_class": ""})
    cards.append({"label": "Records", "value": f"{kpis['records']:,}", "sub": "after cleaning", "delta_class": ""})
    if amount:
        cards.append({"label": f"Average {humanize(amount).lower()}", "value": format_money(kpis.get("average"), currency),
                      "sub": f"median {format_money(kpis.get('median'), currency)}", "delta_class": ""})
    growth = ts.get("second_half_vs_first_half_pct")
    if growth is not None:
        cards.append({"label": "Growth (2nd half vs 1st)", "value": format_pct(growth),
                      "sub": f"best month {ts['best_month']['month']}", "delta_class": _delta_class(growth)})
    monthly = ts.get("monthly") or []
    if len(monthly) >= 2:
        change = monthly[-1].get("change_pct_vs_prev_month")
        cards.append({"label": f"Last month ({monthly[-1]['month']})", "value": format_money(monthly[-1]["total"], currency),
                      "sub": f"{format_pct(change)} vs previous month", "delta_class": _delta_class(change)})
    cards.append({"label": "Data quality", "value": f"{dq['quality_score_after_pct']:.0f}%",
                  "sub": f"was {dq['quality_score_before_pct']:.0f}% before cleaning", "delta_class": "delta-up"})
    return cards


def build_chart_data(analysis: AnalysisResult) -> dict[str, Any]:
    """Prepare the series drawn by Chart.js (monthly trend + top values per dimension)."""
    stats = analysis.stats
    data: dict[str, Any] = {"monthly": None, "dimensions": []}
    ts = stats.get("time_series")
    if ts and ts.get("monthly"):
        data["monthly"] = {"labels": [m["month"] for m in ts["monthly"]], "values": [m["total"] for m in ts["monthly"]]}
    if stats.get("primary_amount_column"):
        for dim, info in stats["breakdowns"].items():
            top = info["top"]
            if len(top) < 2:
                continue
            shown = top[:MAX_CHART_CATEGORIES]
            data["dimensions"].append({"name": dim, "title": humanize(dim).lower(),
                                       "labels": [t["value"] for t in shown], "values": [t["total"] for t in shown],
                                       "distinct": info["distinct_values"]})
    return data


def build_table(dataset: CleanedDataset) -> dict[str, Any]:
    """Serialise the cleaned table (capped) for the dashboard's interactive grid."""
    frame = dataset.frame
    shown = frame.head(MAX_TABLE_ROWS).copy()
    for col in shown.columns:
        if pd.api.types.is_datetime64_any_dtype(shown[col]):
            shown[col] = shown[col].dt.strftime("%Y-%m-%d")
    shown = shown.astype(object).where(shown.notna(), None)
    columns = list(shown.columns)
    numeric = [i for i, c in enumerate(columns) if pd.api.types.is_numeric_dtype(frame[c])]
    rows = [[(v.item() if hasattr(v, "item") else v) for v in row] for row in shown.itertuples(index=False, name=None)]
    filters = []
    for dim in dataset.profile["key_columns"]["dimensions"][:MAX_FILTERS]:
        filters.append({"index": columns.index(dim), "title": humanize(dim).lower(),
                        "options": sorted(str(v) for v in frame[dim].dropna().unique())})
    return {
        "columns": [humanize(c) for c in columns],
        "numeric": numeric,
        "rows": rows,
        "filters": filters,
        "flag_index": columns.index(FLAG_COLUMN) if FLAG_COLUMN in columns else None,
        "total_rows": int(len(frame)),
        "shown_rows": int(len(shown)),
    }


def build_context(dataset: CleanedDataset, analysis: AnalysisResult, settings: Settings,
                  dashboard_file: str | None, report_file: str | None) -> dict[str, Any]:
    """Assemble everything the two templates need."""
    stats = analysis.stats
    amount = stats.get("primary_amount_column")
    currency = dataset.profile.get("currencies", {}).get(amount) if amount else None
    ts = stats.get("time_series") or {}
    issues = dataset.report["issues_fixed"]
    monthly_rows = [{
        "month": m["month"],
        "total": format_money(m["total"], currency),
        "records": m["records"],
        "change": format_pct(m.get("change_pct_vs_prev_month")),
        "delta_class": _delta_class(m.get("change_pct_vs_prev_month")),
    } for m in ts.get("monthly", [])]
    return {
        "source": dataset.source,
        "generated_at": f"{datetime.now():%Y-%m-%d %H:%M}",
        "period": f"{ts['start']} to {ts['end']}" if ts else "",
        "author": settings.your_name,
        "company": settings.your_company,
        "engine": analysis.engine,
        "model": analysis.model,
        "notes": analysis.notes,
        "currency": currency,
        "amount_label": humanize(amount) if amount else "Records",
        "rows_analyzed": stats["rows_analyzed"],
        "insights": analysis.insights,
        "kpis": build_kpis(analysis, currency),
        "chart_data": build_chart_data(analysis),
        "monthly_rows": monthly_rows,
        "table": build_table(dataset),
        "cleaning": dataset.report,
        "quality_before": f"{100 * dataset.report['quality_before']['overall']:.0f}",
        "quality_after": f"{100 * dataset.report['quality_after']['overall']:.0f}",
        "cleaning_stats": [
            ("duplicates removed", issues["duplicates_removed"]),
            ("missing values filled", issues["null_values_filled"]),
            ("values rebuilt from relationships", issues["values_derived_from_relationships"]),
            ("format errors fixed", issues["format_errors_fixed"]),
            ("inconsistent rows flagged", issues["inconsistent_rows_flagged"]),
            ("outliers flagged", issues["outliers_flagged"]),
        ],
        "cleaned_file": dataset.cleaned_path.name if dataset.cleaned_path else "",
        "dashboard_file": dashboard_file,
        "report_file": report_file,
    }


def _environment() -> Environment:
    return Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=select_autoescape(["html", "j2"]),
                       trim_blocks=True, lstrip_blocks=True)


def run(cleaned: list[CleanedDataset], analyses: list[AnalysisResult], settings: Settings) -> list[GeneratedReport]:
    """Agent 4 entry point: render and save the dashboard, report and insights per dataset.

    Args:
        cleaned: Output of the Data Cleaner.
        analyses: Output of the Data Analyst (matched to datasets by name).
        settings: Toggles ``GENERATE_HTML_DASHBOARD`` / ``GENERATE_HTML_REPORT`` and ``REPORTS_PATH``.

    Returns:
        One :class:`GeneratedReport` per dataset successfully rendered.
    """
    env = _environment()
    by_name = {d.name: d for d in cleaned}
    stamp = f"{datetime.now():%Y-%m-%d}"
    outputs: list[GeneratedReport] = []
    settings.reports_path.mkdir(parents=True, exist_ok=True)

    for analysis in analyses:
        dataset = by_name.get(analysis.name)
        if dataset is None:
            logger.error("No cleaned dataset named %s; skipping its report", analysis.name)
            continue
        try:
            dashboard_path = settings.reports_path / f"{stamp}_{analysis.name}_dashboard.html"
            report_path = settings.reports_path / f"{stamp}_{analysis.name}_report.html"
            make_dashboard = settings.generate_html_dashboard
            make_report = settings.generate_html_report
            context = build_context(dataset, analysis, settings,
                                    dashboard_path.name if make_dashboard else None,
                                    report_path.name if make_report else None)

            if make_dashboard:
                dashboard_path.write_text(env.get_template("dashboard.html.j2").render(**context), encoding="utf-8")
                logger.info("Dashboard saved: %s", dashboard_path)
            if make_report:
                report_path.write_text(env.get_template("report.html.j2").render(**context), encoding="utf-8")
                logger.info("Report saved: %s", report_path)

            insights_path = write_json(settings.reports_path / f"{stamp}_{analysis.name}_insights.json", {
                "dataset": analysis.name, "source": analysis.source, "engine": analysis.engine, "model": analysis.model,
                "usage": analysis.usage, "notes": analysis.notes, "insights": analysis.insights, "statistics": analysis.stats,
            })
            outputs.append(GeneratedReport(analysis.name, dashboard_path if make_dashboard else None,
                                           report_path if make_report else None, insights_path))
        except Exception:
            logger.exception("Failed to generate reports for %s", analysis.name)
    return outputs

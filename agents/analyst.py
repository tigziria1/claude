"""Agent 3 - Data Analyst (powered by Claude).

1. Summarises each cleaned table into compact statistics (KPIs, monthly trend,
   breakdown and growth per dimension, outliers, data-quality facts).
2. Sends that summary to Claude, which explains what the numbers show, why,
   where they are heading and what to do - returned as schema-validated JSON.
3. If Claude is unavailable (no API key, network error, refusal...), falls
   back to a rule-based statistical analysis so the pipeline still produces
   a report. The report states which engine produced the insights.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
import numpy as np
import pandas as pd

from config import Settings
from agents.cleaner import FLAG_COLUMN, UNKNOWN_LABEL
from agents.common import AnalysisResult, CleanedDataset, json_default

logger = logging.getLogger("agent.analyst")

MAX_DIMENSIONS = 6
TOP_VALUES = 10

# Models that accept server-side refusal fallbacks (`fallbacks: "default"`).
FALLBACK_CAPABLE_MODELS: frozenset[str] = frozenset({"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"})
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_IMPACT = {"type": "string", "enum": ["high", "medium", "low"]}
INSIGHTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One sentence: the single most important takeaway."},
        "executive_summary": {"type": "string", "description": "3-5 sentences for a busy executive."},
        "key_insights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string", "description": "What is happening and the most likely why."},
                    "evidence": {"type": "string", "description": "The exact figures from the data that support it."},
                    "impact": _IMPACT,
                },
                "required": ["title", "detail", "evidence", "impact"],
                "additionalProperties": False,
            },
        },
        "trends": {"type": "array", "items": {"type": "string"}},
        "anomalies": {"type": "array", "items": {"type": "string"}},
        "forecast": {"type": "string", "description": "Short-term outlook with its assumptions and uncertainty."},
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "rationale": {"type": "string"},
                    "priority": _IMPACT,
                    "expected_impact": {"type": "string"},
                },
                "required": ["action", "rationale", "priority", "expected_impact"],
                "additionalProperties": False,
            },
        },
        "data_quality_notes": {"type": "array", "items": {"type": "string"}},
        "questions_to_investigate": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "executive_summary", "key_insights", "trends", "anomalies", "forecast",
                 "recommendations", "data_quality_notes", "questions_to_investigate"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are the Data Analyst agent of a "Data Intelligence" system used by small and \
mid-sized tech companies that have data everywhere but no analyst to interpret it.

You receive a statistical summary of one business dataset that has already been cleaned. Your job \
is to make the numbers understandable and actionable for a non-technical manager:
- Analyse: what do these numbers show?
- Interpret: why is it probably happening? Separate what the data proves from plausible explanations.
- Predict: where is it heading in the short term, and how confident can we be?
- Recommend: what should the business do next? Make actions specific and tied to the evidence.

Ground every claim in the figures provided and quote them (amounts, percentages, months). Do not \
invent figures that are not in the summary. When the data cannot answer something, say so and list \
it under questions_to_investigate. Mention data-quality caveats that could change a conclusion. \
Give 4-6 key insights and 3-5 recommendations, ordered by importance."""


def _round(value: Any, digits: int = 2) -> Any:
    """Round floats for compact JSON; leave other values unchanged."""
    if isinstance(value, (float, np.floating)):
        return None if np.isnan(value) else round(float(value), digits)
    if isinstance(value, (np.integer,)):
        return int(value)
    return value


def _pct_change(new: float, old: float) -> float | None:
    """Percentage change from ``old`` to ``new`` (None when undefined)."""
    if old in (0, None) or pd.isna(old) or pd.isna(new):
        return None
    return round(100 * (new - old) / abs(old), 1)


def compute_statistics(dataset: CleanedDataset, exclude_inconsistent: bool = True) -> dict[str, Any]:
    """Build the compact statistical summary that is sent to Claude and charted.

    Args:
        dataset: Output of the Data Cleaner.
        exclude_inconsistent: Leave rows flagged ``inconsistent`` (likely
            data-entry errors) out of the figures; their impact is reported.

    Returns:
        A JSON-serialisable dictionary of statistics.
    """
    frame = dataset.frame
    keys = dataset.profile["key_columns"]
    amount: str | None = keys["primary_amount"]
    date_col: str | None = keys["primary_date"]
    dimensions: list[str] = keys["dimensions"][:MAX_DIMENSIONS]

    flags = frame[FLAG_COLUMN] if FLAG_COLUMN in frame else pd.Series("", index=frame.index)
    inconsistent = flags == "inconsistent"
    data = frame.loc[~inconsistent] if exclude_inconsistent else frame

    stats: dict[str, Any] = {
        "dataset": dataset.name,
        "source": dataset.source,
        "rows_analyzed": int(len(data)),
        "primary_amount_column": amount,
        "primary_date_column": date_col,
        "dimensions": dimensions,
    }

    # KPIs
    kpis: dict[str, Any] = {"records": int(len(data))}
    if amount:
        values = data[amount].astype(float)
        kpis.update({
            "total": _round(values.sum()),
            "average": _round(values.mean()),
            "median": _round(values.median()),
            "min": _round(values.min()),
            "max": _round(values.max()),
        })
        top_share = values.sort_values(ascending=False)
        top_n = max(1, len(top_share) // 5)
        kpis["top_20pct_records_share_pct"] = _round(100 * top_share.iloc[:top_n].sum() / values.sum(), 1) if values.sum() else None
    for col in dataset.profile["numeric_columns"]:
        if col != amount:
            kpis[f"{col}_total"] = _round(data[col].astype(float).sum())
            kpis[f"{col}_average"] = _round(data[col].astype(float).mean())
    stats["kpis"] = kpis

    # Time series
    if date_col and amount:
        dated = data.dropna(subset=[date_col])
        if not dated.empty:
            period = dated[date_col].dt.to_period("M")
            monthly = dated.groupby(period)[amount].agg(["sum", "count"]).sort_index()
            months = [str(p) for p in monthly.index]
            series = [{"month": m, "total": _round(s), "records": int(c)} for m, s, c in zip(months, monthly["sum"], monthly["count"])]
            for i in range(1, len(series)):
                series[i]["change_pct_vs_prev_month"] = _pct_change(series[i]["total"], series[i - 1]["total"])
            totals = monthly["sum"]
            half = len(totals) // 2
            time_stats: dict[str, Any] = {
                "start": dated[date_col].min().date().isoformat(),
                "end": dated[date_col].max().date().isoformat(),
                "months": len(series),
                "monthly": series,
                "best_month": {"month": str(totals.idxmax()), "total": _round(totals.max())},
                "worst_month": {"month": str(totals.idxmin()), "total": _round(totals.min())},
                "undated_records_excluded": int(data[date_col].isna().sum()),
            }
            if half:
                time_stats["second_half_vs_first_half_pct"] = _pct_change(totals.iloc[half:].sum(), totals.iloc[:half].sum())
            if len(totals) >= 3:
                slope = np.polyfit(np.arange(len(totals)), totals.to_numpy(dtype=float), 1)[0]
                time_stats["linear_trend_per_month"] = _round(slope)
                time_stats["linear_trend_pct_of_avg_month"] = _round(100 * slope / totals.mean(), 1)
            drops = [(s["month"], s["change_pct_vs_prev_month"]) for s in series[1:] if s.get("change_pct_vs_prev_month") is not None]
            if drops:
                worst = min(drops, key=lambda d: d[1])
                best = max(drops, key=lambda d: d[1])
                time_stats["largest_monthly_drop"] = {"month": worst[0], "change_pct": worst[1]}
                time_stats["largest_monthly_increase"] = {"month": best[0], "change_pct": best[1]}
            stats["time_series"] = time_stats

    # Breakdown per dimension (+ growth between the two halves of the period)
    breakdowns: dict[str, Any] = {}
    midpoint = None
    if date_col and data[date_col].notna().any():
        dated_values = data[date_col].dropna()
        midpoint = dated_values.min() + (dated_values.max() - dated_values.min()) / 2
    for dim in dimensions:
        metric = amount
        grouped = data.groupby(dim, dropna=False)
        table = (grouped[metric].agg(["sum", "count", "mean"]) if metric else grouped.size().to_frame("count"))
        table = table.sort_values("sum" if metric else "count", ascending=False)
        total = float(table["sum"].sum()) if metric else float(table["count"].sum())
        rows: list[dict[str, Any]] = []
        for label, row in table.head(TOP_VALUES).iterrows():
            entry: dict[str, Any] = {"value": str(label), "records": int(row["count"])}
            if metric:
                entry.update({"total": _round(row["sum"]), "share_pct": _round(100 * row["sum"] / total, 1) if total else None,
                              "average": _round(row["mean"])})
                if midpoint is not None:
                    subset = data[data[dim] == label]
                    first = subset.loc[subset[date_col] < midpoint, metric].sum()
                    second = subset.loc[subset[date_col] >= midpoint, metric].sum()
                    entry["growth_second_half_vs_first_half_pct"] = _pct_change(second, first)
            rows.append(entry)
        breakdowns[dim] = {"distinct_values": int(len(table)), "top": rows,
                           "other_values_total": _round(float(table["sum"].iloc[TOP_VALUES:].sum())) if metric and len(table) > TOP_VALUES else None}
    stats["breakdowns"] = breakdowns

    # Data quality and anomalies
    report = dataset.report
    flagged_amount = float(frame.loc[inconsistent, amount].sum()) if amount and inconsistent.any() else 0.0
    outliers = frame.loc[flags == "outlier"]
    stats["data_quality"] = {
        "quality_score_before_pct": _round(100 * report["quality_before"]["overall"], 1),
        "quality_score_after_pct": _round(100 * report["quality_after"]["overall"], 1),
        "rows_before_cleaning": report["rows_before"],
        "rows_after_cleaning": report["rows_after"],
        "issues_fixed": report["issues_fixed"],
        "relationships_detected": report["relationships"],
        "inconsistent_rows_excluded": int(inconsistent.sum()) if exclude_inconsistent else 0,
        "inconsistent_rows_amount": _round(flagged_amount),
        "outlier_rows": int(len(outliers)),
        "outlier_examples": json.loads(outliers.head(5).to_json(orient="records", date_format="iso")) if len(outliers) else [],
        "unknown_labels": {d: int((data[d] == UNKNOWN_LABEL).sum()) for d in dimensions if (data[d] == UNKNOWN_LABEL).any()},
        "warnings": report["warnings"],
    }
    return stats


def _fmt(value: Any) -> str:
    """Human-friendly number formatting for the rule-based insights."""
    if value is None:
        return "n/a"
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.2f}"


def statistical_insights(stats: dict[str, Any]) -> dict[str, Any]:
    """Rule-based insights used when Claude is unavailable (same schema as Claude's output)."""
    amount = stats.get("primary_amount_column") or "records"
    kpis = stats["kpis"]
    insights: list[dict[str, str]] = []
    trends: list[str] = []
    anomalies: list[str] = []
    recommendations: list[dict[str, str]] = []

    ts = stats.get("time_series")
    if ts:
        growth = ts.get("second_half_vs_first_half_pct")
        if growth is not None:
            direction = "grew" if growth >= 0 else "declined"
            insights.append({"title": f"{amount.capitalize()} {direction} {abs(growth):.1f}% in the second half",
                             "detail": f"Comparing the two halves of {ts['start']} to {ts['end']}.",
                             "evidence": f"Best month {ts['best_month']['month']} ({_fmt(ts['best_month']['total'])}), "
                                         f"worst month {ts['worst_month']['month']} ({_fmt(ts['worst_month']['total'])}).",
                             "impact": "high" if abs(growth) >= 10 else "medium"})
        if ts.get("linear_trend_pct_of_avg_month") is not None:
            trends.append(f"Linear trend: {ts['linear_trend_pct_of_avg_month']:+.1f}% of an average month per month.")
        drop = ts.get("largest_monthly_drop")
        if drop and drop["change_pct"] < -15:
            anomalies.append(f"{drop['month']}: {amount} fell {abs(drop['change_pct']):.1f}% versus the previous month.")
            recommendations.append({"action": f"Investigate the {drop['month']} drop",
                                    "rationale": f"A {abs(drop['change_pct']):.1f}% month-on-month fall is the largest in the period.",
                                    "priority": "medium", "expected_impact": "Know whether the dip is seasonal or a fixable problem."})

    for dim, info in list(stats["breakdowns"].items())[:4]:
        top = info["top"]
        if not top or top[0].get("share_pct") is None:
            continue
        leader = top[0]
        insights.append({"title": f"{leader['value']} leads {dim} with {leader['share_pct']:.1f}% of {amount}",
                         "detail": f"{info['distinct_values']} distinct {dim} values.",
                         "evidence": f"{leader['value']}: {_fmt(leader['total'])} over {leader['records']} records.",
                         "impact": "high" if leader["share_pct"] >= 40 else "medium"})
        growers = [t for t in top if t.get("growth_second_half_vs_first_half_pct") is not None
                   and t["records"] >= 10 and t["value"] != UNKNOWN_LABEL]
        if len(growers) >= 2:
            fastest = max(growers, key=lambda t: t["growth_second_half_vs_first_half_pct"])
            slowest = min(growers, key=lambda t: t["growth_second_half_vs_first_half_pct"])
            trends.append(f"{dim}: {fastest['value']} grew fastest ({fastest['growth_second_half_vs_first_half_pct']:+.1f}%), "
                          f"{slowest['value']} slowest ({slowest['growth_second_half_vs_first_half_pct']:+.1f}%).")
            if fastest["growth_second_half_vs_first_half_pct"] > 0:
                recommendations.append({"action": f"Invest more in {fastest['value']} ({dim})",
                                        "rationale": f"Fastest-growing {dim} at {fastest['growth_second_half_vs_first_half_pct']:+.1f}%.",
                                        "priority": "high", "expected_impact": "Compound the strongest growth driver."})

    dq = stats["data_quality"]
    if dq["inconsistent_rows_excluded"]:
        anomalies.append(f"{dq['inconsistent_rows_excluded']} rows break a column relationship ({', '.join(dq['relationships_detected'])}) "
                         f"and were excluded; they total {_fmt(dq['inconsistent_rows_amount'])}.")
        recommendations.append({"action": "Fix the data-entry process behind inconsistent rows",
                                "rationale": f"{dq['inconsistent_rows_excluded']} records disagree with their own quantity x price.",
                                "priority": "medium", "expected_impact": "Reliable totals without manual checks."})
    if dq["outlier_rows"]:
        anomalies.append(f"{dq['outlier_rows']} unusually large or small value(s) flagged as outliers (kept in the totals).")

    headline = insights[0]["title"] if insights else f"{kpis['records']} records analysed"
    return {
        "headline": headline,
        "executive_summary": (f"{kpis['records']} records analysed"
                              + (f" with a total {amount} of {_fmt(kpis.get('total'))} (average {_fmt(kpis.get('average'))})" if kpis.get("total") is not None else "")
                              + f". Data quality improved from {dq['quality_score_before_pct']}% to {dq['quality_score_after_pct']}% after cleaning. "
                              "These insights are rule-based statistics; configure ANTHROPIC_API_KEY for Claude's interpretation."),
        "key_insights": insights,
        "trends": trends,
        "anomalies": anomalies,
        "forecast": (f"If the linear trend holds, {amount} changes by about {_fmt(ts['linear_trend_per_month'])} per month."
                     if ts and ts.get("linear_trend_per_month") is not None else "Not enough dated history for a forecast."),
        "recommendations": recommendations[:5],
        "data_quality_notes": dq["warnings"],
        "questions_to_investigate": [],
    }


def ask_claude(stats: dict[str, Any], settings: Settings) -> tuple[dict[str, Any], dict[str, int], str]:
    """Send the statistics to Claude and return ``(insights, usage, model_used)``.

    Raises:
        anthropic.APIError: On API failures (handled by the caller).
        ValueError: If Claude declines or returns output that is not valid JSON.
    """
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=settings.timeout_seconds, max_retries=2)
    context = f"Company: {settings.your_company}\n" if settings.your_company else ""
    user_message = (
        f"{context}Dataset: {stats['source']}\n"
        "Here is the statistical summary of the cleaned data (JSON). Amounts are in the dataset's own currency.\n\n"
        f"{json.dumps(stats, default=json_default, ensure_ascii=False)}"
    )
    request: dict[str, Any] = {
        "model": settings.claude_model,
        "max_tokens": 16000,
        "system": SYSTEM_PROMPT,
        "output_config": {"effort": settings.claude_effort, "format": {"type": "json_schema", "schema": INSIGHTS_SCHEMA}},
        "messages": [{"role": "user", "content": user_message}],
    }
    if settings.claude_model in FALLBACK_CAPABLE_MODELS:
        # If a safety classifier declines, the API retries on a recommended fallback model.
        request.update(betas=[FALLBACK_BETA], fallbacks="default")
        response = client.beta.messages.create(**request)
    else:
        response = client.messages.create(**request)

    if response.stop_reason == "refusal":
        category = getattr(getattr(response, "stop_details", None), "category", None)
        raise ValueError(f"Claude declined the request (category: {category})")
    if response.stop_reason == "max_tokens":
        raise ValueError("Claude's answer was cut off at max_tokens")
    text = next((block.text for block in response.content if block.type == "text"), "")
    insights = json.loads(text)
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    logger.info("Claude (%s) answered | request_id=%s | %d input / %d output tokens",
                response.model, response._request_id, usage["input_tokens"], usage["output_tokens"])
    return insights, usage, response.model


def analyze_dataset(dataset: CleanedDataset, settings: Settings) -> AnalysisResult:
    """Compute statistics for one dataset and obtain insights (Claude, else rule-based)."""
    stats = compute_statistics(dataset)
    notes: list[str] = []
    if settings.claude_available:
        try:
            insights, usage, model = ask_claude(stats, settings)
            return AnalysisResult(dataset.name, dataset.source, stats, insights, "claude", model, usage)
        except anthropic.AuthenticationError:
            notes.append("Claude API key rejected (401); check ANTHROPIC_API_KEY.")
        except anthropic.PermissionDeniedError:
            notes.append("Claude API key lacks permission for this model (403).")
        except anthropic.NotFoundError:
            notes.append(f"Model '{settings.claude_model}' not found (404); check ANALYST_MODEL.")
        except anthropic.RateLimitError:
            notes.append("Claude API rate limit reached (429) after retries.")
        except anthropic.APIStatusError as exc:
            notes.append(f"Claude API error {exc.status_code}: {exc.message}")
        except anthropic.APIConnectionError:
            notes.append("Could not reach the Claude API (network error or timeout).")
        except (ValueError, json.JSONDecodeError) as exc:
            notes.append(f"Unusable Claude answer: {exc}")
        for note in notes:
            logger.error("%s: %s Falling back to statistical analysis.", dataset.name, note)
    else:
        notes.append("Claude analysis disabled or ANTHROPIC_API_KEY not set; using statistical analysis.")
        logger.warning("%s: %s", dataset.name, notes[-1])
    return AnalysisResult(dataset.name, dataset.source, stats, statistical_insights(stats), "statistical", notes=notes)


def run(datasets: list[CleanedDataset], settings: Settings) -> list[AnalysisResult]:
    """Agent 3 entry point: analyse every cleaned dataset.

    A dataset whose analysis crashes is logged and skipped.
    """
    results: list[AnalysisResult] = []
    for dataset in datasets:
        try:
            result = analyze_dataset(dataset, settings)
        except Exception:
            logger.exception("Failed to analyse %s", dataset.name)
            continue
        logger.info("Analysed %s with %s engine: %d insight(s), %d recommendation(s)", dataset.name, result.engine,
                    len(result.insights.get("key_insights", [])), len(result.insights.get("recommendations", [])))
        results.append(result)
    return results

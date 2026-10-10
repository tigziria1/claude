"""Data Intelligence Agent - orchestrator.

Runs the four agents end to end:

    Agent 1  Ingestion   data/raw/*.csv|xlsx      -> DataFrames + ingestion summary
    Agent 2  Cleaner     DataFrames               -> data/cleaned/*_cleaned.csv + cleaning reports
    Agent 3  Analyst     cleaned data             -> statistics + Claude insights
    Agent 4  Reporter    statistics + insights    -> HTML dashboard + HTML report

Usage:
    python main.py                      # same as --run-all
    python main.py --run-all            # run the full pipeline once
    python main.py --input path/to/dir  # analyse another folder
    python main.py --no-claude          # rule-based insights only (no API call)
    python main.py --schedule 09:00     # run every day at 09:00 (needs APScheduler)
    python main.py --generate-sample    # (re)create data/raw/sample_sales_data.csv first
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from config import PROJECT_ROOT, Settings, load_settings, setup_logging
from agents import analyst, cleaner, ingestion, report_generator
from agents.common import write_json

logger = logging.getLogger("orchestrator")


@dataclass
class PipelineResult:
    """Summary of one end-to-end run (also saved as ``<date>_run_summary.json``)."""

    started_at: str
    success: bool = False
    timings_seconds: dict[str, float] = field(default_factory=dict)
    datasets: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def run_pipeline(settings: Settings, input_path: Path | None = None) -> PipelineResult:
    """Run the four agents in sequence and return a run summary.

    Each agent isolates failures per dataset, so one broken file never stops
    the others. The run fails only when a whole stage yields nothing.
    """
    settings.ensure_directories()
    result = PipelineResult(started_at=datetime.now().isoformat(timespec="seconds"))
    total_start = time.perf_counter()

    def timed(stage: str, func, *args):  # type: ignore[no-untyped-def]
        logger.info("=== %s ===", stage)
        start = time.perf_counter()
        output = func(*args)
        result.timings_seconds[stage] = round(time.perf_counter() - start, 2)
        return output

    try:
        datasets = timed("Agent 1 - Data Ingestion", ingestion.run, settings, input_path)
        if not datasets:
            result.errors.append(f"No readable CSV/Excel files in {input_path or settings.data_input_path}")
            return result
        cleaned = timed("Agent 2 - Data Cleaner", cleaner.run, datasets, settings)
        if not cleaned:
            result.errors.append("Every dataset failed during cleaning")
            return result
        analyses = timed("Agent 3 - Data Analyst", analyst.run, cleaned, settings)
        if not analyses:
            result.errors.append("Every dataset failed during analysis")
            return result
        reports = timed("Agent 4 - Report Generator", report_generator.run, cleaned, analyses, settings)
        if not reports:
            result.errors.append("No report could be generated")
            return result
    except Exception as exc:  # last-resort guard: log, record, never crash silently
        logger.exception("Pipeline aborted")
        result.errors.append(f"{type(exc).__name__}: {exc}")
        return result
    finally:
        result.timings_seconds["total"] = round(time.perf_counter() - total_start, 2)

    analyses_by_name = {a.name: a for a in analyses}
    reports_by_name = {r.name: r for r in reports}
    for ds in cleaned:
        analysis = analyses_by_name.get(ds.name)
        report = reports_by_name.get(ds.name)
        result.datasets.append({
            "name": ds.name,
            "source": ds.source,
            "rows_before": ds.report["rows_before"],
            "rows_after": ds.report["rows_after"],
            "issues_fixed": ds.report["issues_fixed"],
            "quality_before": ds.report["quality_before"]["overall"],
            "quality_after": ds.report["quality_after"]["overall"],
            "insight_engine": analysis.engine if analysis else None,
            "insights_generated": len(analysis.insights.get("key_insights", [])) if analysis else 0,
            "recommendations": len(analysis.insights.get("recommendations", [])) if analysis else 0,
            "claude_tokens": analysis.usage if analysis else {},
            "cleaned_csv": ds.cleaned_path,
            "dashboard": report.dashboard if report else None,
            "report": report.report if report else None,
        })
    result.success = bool(reports)
    return result


def print_summary(result: PipelineResult, settings: Settings) -> None:
    """Log a human-readable recap and save the run summary JSON."""
    summary_path = settings.reports_path / f"{datetime.now():%Y-%m-%d}_run_summary.json"
    write_json(summary_path, result.__dict__)
    logger.info("=" * 64)
    if not result.success:
        for error in result.errors:
            logger.error("Run failed: %s", error)
        logger.info("Run summary: %s", summary_path)
        return
    for ds in result.datasets:
        logger.info("%s: %d -> %d rows | quality %.0f%% -> %.0f%% | %d insights (%s) | %d recommendations",
                    ds["source"], ds["rows_before"], ds["rows_after"], 100 * ds["quality_before"],
                    100 * ds["quality_after"], ds["insights_generated"], ds["insight_engine"], ds["recommendations"])
        if ds["dashboard"]:
            logger.info("  Dashboard -> %s", ds["dashboard"])
        if ds["report"]:
            logger.info("  Report    -> %s", ds["report"])
        logger.info("  Cleaned   -> %s", ds["cleaned_csv"])
    logger.info("Done in %.1fs (target < 120s). Run summary: %s", result.timings_seconds.get("total", 0), summary_path)


def schedule_daily(settings: Settings, at: str, input_path: Path | None) -> None:
    """Run the pipeline every day at ``HH:MM`` (local time) using APScheduler."""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        logger.error("Scheduling needs APScheduler: pip install APScheduler")
        sys.exit(2)
    try:
        hour, minute = (int(part) for part in at.split(":"))
    except ValueError:
        logger.error("Invalid --schedule time %r, expected HH:MM", at)
        sys.exit(2)

    def job() -> None:
        print_summary(run_pipeline(load_settings(), input_path), settings)

    scheduler = BlockingScheduler()
    scheduler.add_job(job, "cron", hour=hour, minute=minute, id="data-intelligence-daily")
    logger.info("Scheduled daily run at %02d:%02d. Press Ctrl+C to stop.", hour, minute)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description="Data Intelligence Agent - ingest, clean, analyse and report.")
    parser.add_argument("--run-all", action="store_true", help="run the full pipeline once (default)")
    parser.add_argument("--input", type=Path, help="folder to read instead of DATA_INPUT_PATH")
    parser.add_argument("--no-claude", action="store_true", help="skip the Claude API and use rule-based insights")
    parser.add_argument("--schedule", metavar="HH:MM", help="run every day at this local time")
    parser.add_argument("--generate-sample", action="store_true", help="regenerate data/raw/sample_sales_data.csv first")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    args = parse_args(argv)
    settings = load_settings()
    if args.no_claude:
        settings.use_claude = False
    setup_logging(settings)
    settings.ensure_directories()

    if args.generate_sample:
        subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "generate_sample_data.py"),
                        "--out", str(settings.data_input_path / "sample_sales_data.csv")], check=True)

    input_path = args.input.resolve() if args.input else None
    if args.schedule:
        schedule_daily(settings, args.schedule, input_path)
        return 0

    logger.info("Data Intelligence Agent starting | input=%s | Claude=%s",
                input_path or settings.data_input_path,
                settings.claude_model if settings.claude_available else "off (rule-based insights)")
    result = run_pipeline(settings, input_path)
    print_summary(result, settings)
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())

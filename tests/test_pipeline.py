"""End-to-end and unit tests for the four agents (no network: Claude is mocked)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

import main
from agents import analyst, cleaner, ingestion, report_generator
from agents.common import parse_number, to_camel_case
from config import PROJECT_ROOT, Settings

SAMPLE = PROJECT_ROOT / "data" / "raw" / "sample_sales_data.csv"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Settings pointing every folder at a temporary directory, Claude off."""
    raw = tmp_path / "raw"
    raw.mkdir()
    return Settings(
        data_input_path=raw,
        data_output_path=tmp_path / "cleaned",
        reports_path=tmp_path / "reports",
        log_file=tmp_path / "logs" / "test.log",
        use_claude=False,
    )


@pytest.fixture()
def sample_settings(settings: Settings) -> Settings:
    """Settings whose input folder contains the demo dataset."""
    shutil.copy(SAMPLE, settings.data_input_path / SAMPLE.name)
    return settings


def test_parse_number_handles_messy_formats() -> None:
    assert parse_number("€1,250.00") == 1250.0
    assert parse_number("1.250,50 EUR") == 1250.5
    assert parse_number("  42 ") == 42.0
    assert parse_number("(12)") == -12.0
    assert parse_number("N/A") is None


def test_camel_case_columns() -> None:
    assert [to_camel_case(c) for c in [" Order ID", "order_date", "PRODUCT", "Revenue (EUR)"]] == [
        "orderId", "orderDate", "product", "revenue"]


def test_ingestion_reads_latin1_semicolon_csv_and_excel(settings: Settings) -> None:
    (settings.data_input_path / "legacy.csv").write_bytes("Ville;Montant\nMontréal;1 200,50\nQuébec;300\n".encode("cp1252"))
    with pd.ExcelWriter(settings.data_input_path / "book.xlsx") as writer:
        pd.DataFrame({"a": [1, 2]}).to_excel(writer, sheet_name="Q1", index=False)
        pd.DataFrame({"b": ["x"]}).to_excel(writer, sheet_name="Q2", index=False)
    (settings.data_input_path / "notes.pdf").write_text("ignored")

    datasets = {d.name: d for d in ingestion.run(settings)}
    assert set(datasets) == {"legacy", "book_Q1", "book_Q2"}
    assert datasets["legacy"].frame.iloc[0, 0] == "Montréal"
    assert datasets["legacy"].data_types["Montant"] == "numeric"


def test_cleaner_fixes_sample_data(sample_settings: Settings) -> None:
    [dataset] = cleaner.run(ingestion.run(sample_settings), sample_settings)
    report, frame = dataset.report, dataset.frame
    fixed = report["issues_fixed"]

    assert report["rows_before"] == 620 and report["rows_after"] == 600
    assert fixed["duplicates_removed"] == 20
    assert fixed["null_values_filled"] > 0 and fixed["format_errors_fixed"] > 0
    assert report["relationships"] == ["revenue = quantity x unitPrice"]
    assert fixed["inconsistent_rows_flagged"] > 0  # the injected x10 data-entry errors
    assert report["quality_after"]["overall"] > report["quality_before"]["overall"]
    assert pd.api.types.is_datetime64_any_dtype(frame["orderDate"])
    assert set(frame["region"]) <= {"Europe", "North America", "Asia Pacific", "Middle East", "Unknown"}
    assert frame["revenue"].notna().all()
    assert dataset.profile["key_columns"]["primary_amount"] == "revenue"
    assert dataset.profile["currencies"]["revenue"] == "EUR"
    assert dataset.cleaned_path is not None and dataset.cleaned_path.exists()


def test_full_pipeline_offline_writes_reports(sample_settings: Settings) -> None:
    result = main.run_pipeline(sample_settings)
    assert result.success, result.errors
    [ds] = result.datasets
    assert ds["insight_engine"] == "statistical"
    html = Path(ds["dashboard"]).read_text(encoding="utf-8")
    assert "€1,081,244" in html and "chart-monthly" in html
    assert "Data Intelligence Report" in Path(ds["report"]).read_text(encoding="utf-8")


def test_pipeline_fails_cleanly_without_files(settings: Settings) -> None:
    result = main.run_pipeline(settings)
    assert not result.success
    assert "No readable CSV/Excel files" in result.errors[0]


class _FakeMessages:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


def _fake_client(monkeypatch: pytest.MonkeyPatch, response: Any) -> _FakeMessages:
    messages = _FakeMessages(response)
    client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))
    monkeypatch.setattr(analyst.anthropic, "Anthropic", lambda **_: client)
    return messages


def _response(stop_reason: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop_reason, stop_details=None, model="claude-opus-5-5", _request_id="req_test",
                           content=[SimpleNamespace(type="text", text=text)],
                           usage=SimpleNamespace(input_tokens=1000, output_tokens=500))


def test_analyst_uses_claude_structured_output(sample_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    sample_settings.use_claude = True
    sample_settings.anthropic_api_key = "sk-test"
    payload = {"headline": "Europe drives growth", "executive_summary": "Summary.",
               "key_insights": [{"title": "t", "detail": "d", "evidence": "e", "impact": "high"}],
               "trends": [], "anomalies": [], "forecast": "f",
               "recommendations": [{"action": "a", "rationale": "r", "priority": "high", "expected_impact": "x"}],
               "data_quality_notes": [], "questions_to_investigate": []}
    messages = _fake_client(monkeypatch, _response("end_turn", json.dumps(payload)))

    cleaned = cleaner.run(ingestion.run(sample_settings), sample_settings)
    [result] = analyst.run(cleaned, sample_settings)

    assert result.engine == "claude" and result.insights["headline"] == "Europe drives growth"
    request = messages.calls[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["fallbacks"] == "default"
    assert request["output_config"]["format"]["schema"] == analyst.INSIGHTS_SCHEMA
    assert "revenue" in request["messages"][0]["content"]

    reports = report_generator.run(cleaned, [result], sample_settings)
    assert "Insights by Claude" in reports[0].dashboard.read_text(encoding="utf-8")


def test_analyst_falls_back_when_claude_refuses(sample_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    sample_settings.use_claude = True
    sample_settings.anthropic_api_key = "sk-test"
    _fake_client(monkeypatch, _response("refusal", ""))

    [result] = analyst.run(cleaner.run(ingestion.run(sample_settings), sample_settings), sample_settings)
    assert result.engine == "statistical"
    assert any("declined" in note for note in result.notes)
    assert result.insights["key_insights"]

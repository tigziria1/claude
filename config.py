"""Central configuration for the Data Intelligence Agent.

Every setting is read from environment variables (loaded from ``.env`` when
present) so that no path, flag or API key is hardcoded in the agents.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT: Path = Path(__file__).resolve().parent

# Values shipped in the .env template that must not be treated as real keys.
_PLACEHOLDER_KEYS: frozenset[str] = frozenset({"", "sk-xxxxx", "your-api-key", "changeme"})


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable (``true/1/yes/on`` are truthy)."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back on invalid input."""
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        logging.getLogger(__name__).warning("Invalid integer for %s=%r, using %s", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    """Read a float environment variable, falling back on invalid input."""
    raw = os.getenv(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        logging.getLogger(__name__).warning("Invalid float for %s=%r, using %s", name, raw, default)
        return default


def _env_path(name: str, default: str) -> Path:
    """Read a path environment variable, resolved relative to the project root."""
    path = Path(os.getenv(name, default) or default).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


@dataclass
class Settings:
    """All runtime settings of the pipeline.

    Attributes mirror the keys documented in ``.env.example``.
    """

    your_name: str = "DataBot"
    your_company: str = ""

    data_input_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "raw")
    data_output_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "cleaned")
    reports_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "reports")

    support_csv: bool = True
    support_excel: bool = True

    generate_html_dashboard: bool = True
    generate_html_report: bool = True

    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "high"
    use_claude: bool = True

    log_level: str = "INFO"
    log_file: Path = field(default_factory=lambda: PROJECT_ROOT / "logs" / "databot.log")
    save_cleaning_report: bool = True

    auto_fix_nulls: bool = True
    auto_remove_duplicates: bool = True
    auto_detect_outliers: bool = True
    outlier_threshold: float = 2.5

    max_rows_per_file: int = 100_000
    chunk_size_processing: int = 10_000
    timeout_seconds: int = 300

    @property
    def claude_available(self) -> bool:
        """True when Claude analysis is enabled and a real API key is configured."""
        return self.use_claude and bool(self.anthropic_api_key)

    def ensure_directories(self) -> None:
        """Create every input/output directory the pipeline writes to."""
        for directory in (self.data_input_path, self.data_output_path, self.reports_path, self.log_file.parent):
            directory.mkdir(parents=True, exist_ok=True)


def load_settings(env_file: Path | None = None) -> Settings:
    """Load settings from ``.env`` (if present) and the process environment.

    Args:
        env_file: Optional explicit path to a dotenv file. Defaults to
            ``<project>/.env``. Existing environment variables take precedence.

    Returns:
        A populated :class:`Settings` instance.
    """
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if api_key in _PLACEHOLDER_KEYS:
        api_key = ""

    return Settings(
        your_name=os.getenv("YOUR_NAME", "DataBot").strip() or "DataBot",
        your_company=os.getenv("YOUR_COMPANY", "").strip(),
        data_input_path=_env_path("DATA_INPUT_PATH", "./data/raw/"),
        data_output_path=_env_path("DATA_OUTPUT_PATH", "./data/cleaned/"),
        reports_path=_env_path("REPORTS_PATH", "./data/reports/"),
        support_csv=_env_bool("SUPPORT_CSV", True),
        support_excel=_env_bool("SUPPORT_EXCEL", True),
        generate_html_dashboard=_env_bool("GENERATE_HTML_DASHBOARD", True),
        generate_html_report=_env_bool("GENERATE_HTML_REPORT", True),
        anthropic_api_key=api_key or None,
        claude_model=os.getenv("ANALYST_MODEL", "claude-opus-5-5").strip() or "claude-opus-5-5",
        claude_effort=os.getenv("ANALYST_EFFORT", "high").strip() or "high",
        use_claude=_env_bool("USE_CLAUDE", True),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        log_file=_env_path("LOG_FILE", "./logs/databot.log"),
        save_cleaning_report=_env_bool("SAVE_CLEANING_REPORT", True),
        auto_fix_nulls=_env_bool("AUTO_FIX_NULLS", True),
        auto_remove_duplicates=_env_bool("AUTO_REMOVE_DUPLICATES", True),
        auto_detect_outliers=_env_bool("AUTO_DETECT_OUTLIERS", True),
        outlier_threshold=_env_float("OUTLIER_THRESHOLD", 2.5),
        max_rows_per_file=_env_int("MAX_ROWS_PER_FILE", 100_000),
        chunk_size_processing=_env_int("CHUNK_SIZE_PROCESSING", 10_000),
        timeout_seconds=_env_int("TIMEOUT_SECONDS", 300),
    )


def setup_logging(settings: Settings) -> None:
    """Configure root logging to both the console and a rotating log file."""
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")

    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level, logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(settings.log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # The HTTP client logs every request at INFO; keep the pipeline log readable.
    for noisy in ("httpx", "httpcore", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

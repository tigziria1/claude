# Data Intelligence Agent

Turns messy business spreadsheets into clean data, AI insights and a ready-to-share dashboard, automatically.

```
data/raw/*.csv|xlsx ─▶ 1 Ingestion ─▶ 2 Cleaner ─▶ 3 Analyst (Claude) ─▶ 4 Report Generator ─▶ data/reports/*.html
```

| Agent | Module | What it does |
|---|---|---|
| 1. Data Ingestion | `agents/ingestion.py` | Scans `data/raw/`, reads CSV (encoding + delimiter detection, chunked) and every Excel sheet, infers column types, saves an ingestion summary JSON. |
| 2. Data Cleaner | `agents/cleaner.py` | camelCase column names, null placeholders (`N/A`, `-`, `null`…), currency/number parsing (`€1,250.00` → `1250.0`), mixed date formats → ISO, label casing/spacing, duplicates, missing values (rebuilt from detected relationships like `revenue = quantity × unitPrice`, then median / `Unknown`), outliers and inconsistent rows flagged (kept, never silently deleted), column roles, quality score before/after. |
| 3. Data Analyst | `agents/analyst.py` | Computes KPIs, monthly trend, growth per segment and anomalies, then asks Claude to analyse, interpret, forecast and recommend. The answer is schema-validated JSON. Without an API key (or if the call fails) it falls back to rule-based insights, and the report says so. |
| 4. Report Generator | `agents/report_generator.py` | Interactive HTML dashboard (KPI cards, charts with tooltips, searchable/filterable data table, light/dark) + printable HTML report (executive summary, insights, recommendations, data quality, signature) + insights JSON. |

`main.py` orchestrates the four agents, times each stage and writes a run summary.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # then set ANTHROPIC_API_KEY, YOUR_NAME, YOUR_COMPANY
python main.py --run-all      # analyses everything in data/raw/
```

Open `data/reports/<date>_<file>_dashboard.html` in a browser.

The repo ships with `data/raw/sample_sales_data.csv`, a deliberately chaotic 620-row sales export (duplicates, 4 date formats, `€`/`EUR` amounts, `N/A` placeholders, inconsistent casing, ×10 typing errors). Regenerate it with `python main.py --generate-sample`.

## Commands

```bash
python main.py                      # full pipeline (same as --run-all)
python main.py --input ~/exports    # analyse another folder
python main.py --no-claude          # rule-based insights only, no API call
python main.py --schedule 09:00     # run every day at 09:00 (APScheduler)
python -m pytest -q                 # tests (Claude is mocked, no network)
```

## Output

```
data/
├── raw/                                     # your original files (never modified)
├── cleaned/<file>_cleaned.csv               # clean data, ISO dates, qualityFlag column
└── reports/
    ├── <date>_<file>_dashboard.html         # ← open this
    ├── <date>_<file>_report.html            # printable report ("Print / Save as PDF")
    ├── <date>_<file>_insights.json          # statistics + insights
    ├── cleaning_report_<date>_<file>.json   # every fix, counted
    ├── <date>_ingestion_summary.json
    └── <date>_run_summary.json              # timings, quality, insight counts
logs/databot.log
```

Charts load Chart.js from a CDN, so they need an internet connection. Everything else works offline.

## Configuration (`.env`)

| Key | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Enables Claude analysis. Placeholder `sk-xxxxx` counts as unset. |
| `ANALYST_MODEL` | `claude-opus-5-5` | Model used by Agent 3. |
| `ANALYST_EFFORT` | `high` | `low`…`max`: depth of Claude's reasoning vs token cost. |
| `USE_CLAUDE` | `true` | Set `false` to force rule-based insights. |
| `DATA_INPUT_PATH` / `DATA_OUTPUT_PATH` / `REPORTS_PATH` | `./data/...` | Folders. |
| `SUPPORT_CSV` / `SUPPORT_EXCEL` | `true` | File types to ingest. |
| `GENERATE_HTML_DASHBOARD` / `GENERATE_HTML_REPORT` | `true` | Outputs to render. |
| `AUTO_FIX_NULLS` / `AUTO_REMOVE_DUPLICATES` / `AUTO_DETECT_OUTLIERS` | `true` | Cleaning steps. |
| `OUTLIER_THRESHOLD` | `2.5` | z-score (log scale for skewed money columns). |
| `MAX_ROWS_PER_FILE` / `CHUNK_SIZE_PROCESSING` | `100000` / `10000` | Size limits. |
| `TIMEOUT_SECONDS` | `300` | Claude API timeout. |
| `LOG_LEVEL` / `LOG_FILE` | `INFO` / `./logs/databot.log` | Logging. |

## How the analysis decides things

- **Inconsistent rows** (e.g. revenue ≠ quantity × unit price) are likely typing errors: they stay in the cleaned CSV with `qualityFlag=inconsistent` but are excluded from the figures, and the report states how many and how much they total.
- **Outliers** are flagged (`qualityFlag=outlier`) but kept in totals.
- **Rows without a valid date** are kept but excluded from the monthly trend.
- **Quality score** = 40 % completeness + 30 % validity (values in canonical format) + 30 % uniqueness.
- **Claude refusals**: requests use server-side fallbacks (`fallbacks: "default"`), so a declined request is retried on a recommended model. If it still fails, the rule-based analysis is used and the reason is shown on the dashboard.

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | `pip install -r requirements.txt` |
| Report says "Claude not used" | Set a real `ANTHROPIC_API_KEY` in `.env`; the notice on the dashboard gives the exact reason (401, network…). |
| A file is skipped | Check `logs/databot.log`; only `.csv .tsv .txt .xlsx .xlsm .xls` are read (`.xls` needs `xlrd`). |
| Wrong amount column chosen | The analyst prefers columns named revenue/sales/amount/total. Rename the column in the source file. |

See `CLAUDE.md` for the design brief.

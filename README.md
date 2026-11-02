# Harbourview Dashboard

A local, single-user Streamlit dashboard for Harbourview operational reporting. Resident-level metrics are calculated by `metrics.py`; the dashboard reads aggregate tables from DuckDB.

## Features

- Executive overview, referral funnel, occupancy, length of stay, follow-up outcomes, and data-quality pages.
- Validated aggregate reporting with report-period parameters and source provenance.
- A guided workflow to preview and add one resident record, recalculate aggregates, and publish a new report version.
- Optional Gemini-powered AI Analyst. Queries run against approved aggregate reports; resident-level records are not sent to the model.
- Versioned report storage that keeps each raw-data snapshot, aggregate export, and DuckDB file together.

## Requirements

- Python 3.11 or later
- Dependencies listed in `requirements.txt`

## Quick start

```bash
python -m venv .venv
```

Activate the environment, then install dependencies and start the app:

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

Without resident-entry configuration, the dashboard can still read the bundled or otherwise selected aggregate database. The Add Resident page remains unavailable until a data source is explicitly configured and initialized.

## Configure resident entry

Copy `report_config.example.json` to `report_config.json` and set the source CSV and report parameters:

```json
{
  "source_csv": "data/harbourview_residents.csv",
  "version_root": "report_store",
  "report": {
    "as_of": "2026-01-15",
    "fiscal_year": 2025,
    "capacity": 24,
    "followup_anchor": "discharge",
    "occupancy_start": "2025-01-01"
  }
}
```

The paths and dates above are examples. Confirm the source file, snapshot cutoff, fiscal year, bed capacity, follow-up anchor, and occupancy start date against the actual data before use. The example cutoff date does not establish the actual extraction date. Relative paths are resolved from the configuration file's directory. Set `HARBOURVIEW_CONFIG` to use a configuration file elsewhere.

Initialize and inspect the first report version explicitly:

```bash
python report_versions.py initialize --config report_config.json
python report_versions.py status --config report_config.json
```

Initialization reads the configured CSV and publishes a versioned report. It does not overwrite the source CSV or an existing report database. The dashboard does not run full calculations on ordinary page reruns or filter changes.

To generate aggregate exports and a new DuckDB file without publishing a resident-entry version, use new output paths and explicit report parameters:

```bash
python metrics.py data/harbourview_residents.csv \
  --as-of 2026-01-15 \
  --fiscal-year 2025 \
  --capacity 24 \
  --followup-anchor discharge \
  --occupancy-start 2025-01-01 \
  --out scratch/new-aggregates
python duckdb_store.py --source scratch/new-aggregates --db scratch/new-report.duckdb
```

Confirm all example dates and parameters against the source data before running these commands.

## Add a resident

Open **Add Resident Record** from the app navigation. Review the configured data source, active version, and report parameters; enter the record; then preview it before confirming submission.

Dates may be left blank and are not filled with today's date. The form checks the resident ID, field formats, and duplicate IDs. It displays data-quality warnings before submission. On confirmation, the app builds a candidate source snapshot, recalculates and validates aggregates, imports a new DuckDB file, and only then activates the new version. Existing versions are retained.

The new resident may fall outside the configured reporting period. The app does not change report dates to force the record into current metrics. If calculation or import fails, the active version remains in use and the form can be retried after the issue is resolved.

## Report versions and data handling

The configured version directory contains a `current.json` pointer and immutable version directories. Each version includes its raw CSV snapshot, aggregate exports, report database, and manifest with report parameters and provenance. The current pointer is updated only after the candidate version passes validation.

`db.py` opens aggregate databases read-only. Raw resident data is not appended to aggregate tables and is not included in dashboard aggregate downloads. Protect the configured source and version directory according to your organization's data-handling requirements.

The sidebar can display a different historical DuckDB report. The app identifies the report being viewed separately from the active version updated by resident entry.

## AI Analyst

The AI Analyst is available on the Overview page. Gemini is the default planner and requires `GEMINI_API_KEY` (or `GOOGLE_API_KEY`). Set `GEMINI_MODEL` to override the default model. The dashboard's standard pages do not require an API key.

The planner produces a structured request that is validated locally before fixed, read-only aggregate queries run. The model does not receive query results or resident records. See [`PART_B_README.md`](PART_B_README.md) for configuration details, supported requests, and data boundaries.

## Tests

Run the test suite from the repository root:

```bash
python -B -m unittest discover -s tests -v
```

Tests use synthetic data and temporary directories; they do not add test residents to a configured source CSV.

## Scope and limitations

This application is intended for local, single-user operation. It supports adding records only; editing, deleting, bulk import, and multi-user authorization are out of scope. Historical outcome dates and bed registers may be incomplete. Unknown discharge dates are represented as occupancy bounds, and valid occupancy rates above 100% are retained.
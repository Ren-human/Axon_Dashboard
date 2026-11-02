"""Read-only data boundary. Keep SQL/schema decisions out of page layouts."""
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

TABLES = ('run_metadata', 'funnel', 'monthly_occupancy', 'los', 'outcomes', 'data_quality_summary')

# Conservative aliases only. Add known, semantically equivalent names here.
# A percentage column is NOT automatically interchangeable with a fraction.
ALIASES = {
    'stage': ('stage_name', 'milestone'), 'n': ('count', 'resident_count'),
    'month': ('report_month',), 'cohort': ('cohort_name', 'stay_type'),
    'median_days': ('median_los_days',), 'p90_days': ('p90_los_days',),
    'horizon_months': ('followup_months',), 'due_n': ('eligible_due_n',),
    'rule': ('rule_name', 'check_name'), 'severity': ('level',),
}


def normalize(frame):
    """Match case/spacing and approved aliases; never guess arbitrary numeric fields."""
    frame = frame.copy()
    frame.columns = [str(c).strip().lower().replace(' ', '_') for c in frame.columns]
    if frame.columns.duplicated().any():
        raise ValueError('Column names collide after normalization. Rename them in the source.')
    for canonical, aliases in ALIASES.items():
        if canonical not in frame:
            for alias in aliases:
                if alias in frame:
                    frame = frame.rename(columns={alias: canonical})
                    break
    return frame


@st.cache_data(ttl=60, show_spinner=False)
def read_table(path, table, modified_ns, size):
    # mtime/size are cache keys: replacing the file invalidates cached data.
    # Only whitelisted identifiers enter SQL; values should use SQL parameters.
    if table not in TABLES:
        raise ValueError('Unsupported table')
    with duckdb.connect(path, read_only=True) as con:
        return con.execute(f'SELECT * FROM main."{table}"').df()


def load(path):
    result, problems = {}, {}
    stat = Path(path).stat()
    for table in TABLES:
        try:
            result[table] = normalize(read_table(str(path), table, stat.st_mtime_ns, stat.st_size))
        except (duckdb.Error, ValueError) as exc:
            result[table] = pd.DataFrame()
            problems[table] = str(exc)
    return result, problems


def select_run(frame, run_id):
    # Filtering aggregate tables by arbitrary resident dates would be misleading.
    if run_id is not None and 'run_id' in frame:
        return frame[frame['run_id'].astype(str) == str(run_id)].copy()
    return frame.copy()


def numeric(frame, columns):
    result = frame.copy()
    for col in columns:
        if col in result:
            result[col] = pd.to_numeric(result[col], errors='coerce')
    return result

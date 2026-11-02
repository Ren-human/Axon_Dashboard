"""Streamlit entry point. Reads active reports; never computes on a rerun."""
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from db import load, TABLES
import report_versions as versions

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title='Harbourview | Learn', page_icon='🏠', layout='wide')
st.title('Harbourview | Operational dashboard')

active_db, manifest, config_problem = None, None, None
try:
    cfg = versions.load_config()
    manifest = versions.current(cfg)
    if manifest:
        _, active_db = versions.active_paths(cfg, manifest)
except (OSError, ValueError, KeyError) as exc:
    config_problem = str(exc)

active_text = str(active_db) if active_db else None
previous_active = st.session_state.get('last_active_db')
if 'selected_report_path' not in st.session_state:
    st.session_state['selected_report_path'] = os.environ.get(
        'HARBOURVIEW_DB', active_text or str(ROOT / 'database' / 'harbourview.duckdb'))
if st.session_state.pop('switch_to_active', False) and active_text:
    st.session_state['selected_report_path'] = active_text
elif (active_text and previous_active is not None and previous_active != active_text
      and st.session_state['selected_report_path'] == previous_active):
    st.session_state['selected_report_path'] = active_text
st.session_state['last_active_db'] = active_text
# Durable selection survives Streamlit widget cleanup on page changes.
st.session_state['report_db'] = st.session_state['selected_report_path']


def remember_database():
    st.session_state['selected_report_path'] = st.session_state['report_db']

with st.sidebar:
    st.header('Data & filters')
    path_text = st.text_input('DuckDB file', key='report_db', on_change=remember_database)
    if st.button('Reload database'):
        st.cache_data.clear()
    if manifest:
        st.caption(f'Active version for resident entry: {manifest["version"]}')
    elif config_problem:
        st.caption('Resident entry is not configured or the configuration is invalid. Analysis pages remain available.')
    else:
        st.caption('Resident entry has not been initialized. Analysis pages remain available.')

path = Path(path_text).expanduser()
if not path.is_absolute():
    path = ROOT / path
tables, problems = {name: pd.DataFrame() for name in TABLES}, {}
try:
    if not path.is_file():
        raise ValueError(f'Database not found: {path}')
    tables, problems = load(path)
except (OSError, ValueError) as exc:
    st.error(f'Unable to open database: {exc}')
    problems = {name: str(exc) for name in TABLES}

meta = tables['run_metadata']
if len(meta) == 1:
    row = meta.iloc[0]
    st.caption(' · '.join(f'{label}: {row.get(col, "unavailable")}' for label, col in
                         [('Cutoff', 'as_of'), ('Fiscal year', 'fiscal_year'), ('Beds', 'bed_capacity')]))
elif len(meta) > 1:
    st.warning('One database must represent one report. Ambiguous aggregates have been withheld.')
    for name in TABLES:
        if name != 'run_metadata':
            tables[name] = tables[name].iloc[:0]
            problems[name] = 'Multiple metadata rows: single-report database required.'
if problems:
    st.warning('Some aggregate tables could not be read. Affected pages show details; other pages remain usable.')
st.caption(f'Currently viewing report: {path}')
if manifest and path.resolve() != active_db.resolve():
    st.info('You are viewing another report. Adding a resident updates only the configured data source and its active report version; it does not modify the historical report currently being viewed.')
    if st.button('Open the active report for resident entry'):
        st.session_state['switch_to_active'] = True
        st.rerun()
elif manifest:
    st.caption(f'Active report version: {manifest["version"]}')
st.session_state['tables'] = tables
st.session_state['problems'] = problems
st.session_state['db_path'] = str(path)

page = st.navigation([
    st.Page('pages/overview.py', title='Overview', default=True),
    st.Page('pages/funnel.py', title='Referral funnel', url_path='funnel'),
    st.Page('pages/occupancy.py', title='Occupancy', url_path='occupancy'),
    st.Page('pages/los.py', title='Length of stay', url_path='los'),
    st.Page('pages/outcomes.py', title='Follow-up outcomes', url_path='outcomes'),
    st.Page('pages/quality.py', title='Data quality', url_path='quality'),
    st.Page('pages/add_resident.py', title='Add Resident Record', url_path='add-resident'),
])
page.run()

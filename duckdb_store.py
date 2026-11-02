"""Import precomputed aggregates into a NEW, single-report DuckDB file."""
import argparse
import json
import os
from pathlib import Path

import duckdb
import pandas as pd

from summary_validation import outcome_summary, occupancy_summary, valid_count

ROOT = Path(__file__).resolve().parent
TABLES = ('funnel', 'monthly_occupancy', 'los', 'outcomes', 'data_quality_summary')
REQUIRED = {
    'funnel': {'stage', 'n', 'previous_stage_n', 'conversion_from_previous'},
    'monthly_occupancy': {'month', 'known_bed_days_lower', 'available_bed_days'},
    'los': {'cohort', 'n', 'median_days', 'p90_days'},
    'outcomes': {'horizon_months', 'known_outcome_n', 'due_n', 'ascertainment_rate'},
    'data_quality_summary': {'severity', 'rule', 'n'},
}


def source_frames(source):
    source = Path(source)
    frames = {name: pd.read_csv(source / f'{name}.csv') for name in TABLES}
    for name, required in REQUIRED.items():
        if not required <= set(frames[name]):
            raise ValueError(f'{name}: missing required columns {sorted(required - set(frames[name]))}')
    metadata = json.loads((source / 'metrics.json').read_text(encoding='utf-8'))['metadata']
    frames['run_metadata'] = pd.DataFrame([{key: json.dumps(value) if isinstance(value, (list, dict))
                                          else value for key, value in metadata.items()}])
    return frames


def build(source, destination):
    destination = Path(destination)
    frames = source_frames(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.with_name(destination.name + '.create.lock')
    fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        if destination.exists():
            raise FileExistsError(f'{destination} already exists; choose a new --db path.')
        with duckdb.connect(str(destination)) as con:
            con.execute('BEGIN TRANSACTION')
            for name, frame in frames.items():
                if name == 'data_quality_summary' and frame.empty:
                    con.execute('CREATE TABLE data_quality_summary (severity VARCHAR, rule VARCHAR, n BIGINT)')
                else:
                    con.register('incoming', frame)
                    con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM incoming')
                    con.unregister('incoming')
            con.execute('COMMIT')
    finally:
        lock.unlink()


def validate_database(path, source):
    """Read-only integrity/reconciliation gate before activation."""
    expected = source_frames(source)
    with duckdb.connect(str(path), read_only=True) as con:
        names = {r[0] for r in con.execute('SHOW TABLES').fetchall()}
        if names != set(expected):
            raise ValueError('Expected exactly the six dashboard aggregate tables')
        frames = {}
        for name, target in expected.items():
            actual = con.execute(f'SELECT * FROM "{name}"').df()
            pd.testing.assert_frame_equal(actual, target, check_dtype=False, check_exact=False,
                                          rtol=1e-8, atol=1e-10, check_index_type=False)
            frames[name] = actual
    meta = frames['run_metadata']
    if len(meta) != 1 or not {'input_sha256', 'metrics_version', 'as_of', 'snapshot_as_of'} <= set(meta):
        raise ValueError('Missing single-report provenance metadata')
    for horizon in (6, 12):
        summary, issue = outcome_summary(frames['outcomes'], horizon)
        if summary is None:
            raise ValueError(issue)
    if len(frames['outcomes']) != 2:
        raise ValueError('Expected exactly two outcome horizons')
    summary, issue = occupancy_summary(frames['monthly_occupancy'], meta)
    if summary is None or summary['available'] <= 0:
        raise ValueError(issue or 'No available bed-days in the generated report')
    funnel = frames['funnel']
    if funnel['stage'].tolist() != ['referral', 'intake', 'admission', 'discharge']:
        raise ValueError('Invalid funnel stages')
    from summary_validation import rate_matches, number
    previous = None
    for _, row in funnel.iterrows():
        if not valid_count(row['n']) or not valid_count(row['previous_stage_n']):
            raise ValueError('Invalid funnel count')
        n, denominator = number(row['n']), number(row['previous_stage_n'])
        if n > denominator or (previous is not None and denominator != previous):
            raise ValueError('Funnel counts do not reconcile')
        if not rate_matches(row['conversion_from_previous'], n, denominator):
            raise ValueError('Funnel conversion does not reconcile')
        previous = n
    quality = frames['data_quality_summary']
    if not all(valid_count(n) for n in quality['n']):
        raise ValueError('Invalid quality count')
    if sum(quality['n']) != meta.iloc[0]['issue_count']:
        raise ValueError('Quality counts do not reconcile to metadata')
    if len(frames['los']) != 3 or not all(valid_count(n) for n in frames['los']['n']):
        raise ValueError('Invalid LOS aggregates')
    return frames


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Directory of exported aggregate CSV and metrics.json')
    parser.add_argument('--db', type=Path, required=True, help='New database file; existing files are refused')
    args = parser.parse_args()
    build(args.source, args.db)
    validate_database(args.db, args.source)
    print(f'Created and validated {args.db}')

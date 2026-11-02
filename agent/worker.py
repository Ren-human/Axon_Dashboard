"""Private subprocess entry point. Only fixed, aggregate SELECT templates exist."""
import hashlib
import json
from pathlib import Path
import sys
import duckdb
from events import monthly_activity, ActivitySourceError

COLUMNS = {
    'funnel': ('funnel', 'stage,n,previous_stage_n,conversion_from_previous,conversion_from_referrals'),
    'occupancy': ('monthly_occupancy', 'month,period_start,period_end_inclusive,observed_days,available_bed_days,known_bed_days_lower,bed_days_upper,occupancy_lower,occupancy_upper'),
    'outcomes': ('outcomes', 'horizon_months,due_n,known_outcome_n,ascertainment_rate,engaged_in_recovery,relapse_reported,lost_to_follow_up,unknown,missing,due_but_marked_not_yet_due,unrecognized,relapse_fraction_all_due'),
    'los': ('los', 'cohort,n,median_days,p90_days'),
    'quality': ('data_quality_summary', 'severity,rule,n'),
    'metadata': ('run_metadata', 'as_of,snapshot_as_of,fiscal_year,bed_capacity,occupancy_start,metrics_version'),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(request):
    required = {'path','fingerprint','metrics'}
    if not required <= set(request) or set(request)-required-{'events_source'} or not request['metrics'] or len(request['metrics']) > 6:
        raise ValueError('Invalid query plan.')
    if any((m not in COLUMNS and m != 'monthly_activity') or m == 'metadata' for m in request['metrics']):
        raise ValueError('Unsupported metric.')
    has_activity = 'monthly_activity' in request['metrics']
    if has_activity and (not isinstance(request.get('events_source'),dict) or set(request['events_source']) != {'path'}):
        raise ValueError('Monthly activity source is missing.')
    if digest(request['path']) != request['fingerprint']:
        raise ValueError('Report integrity check failed.')
    settings = dict(enable_external_access='false', autoload_known_extensions='false',
                    autoinstall_known_extensions='false', threads='1', memory_limit='256MB',
                    max_temp_directory_size='0B')
    tables = {}
    with duckdb.connect(request['path'], read_only=True, config=settings) as con:
        base = {row[0] for row in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE'").fetchall()}
        expected = {x[0] for x in COLUMNS.values()}
        if base != expected:
            raise ValueError('Expected exactly six aggregate base tables.')
        for metric in ['metadata', *request['metrics']]:
            if metric == 'monthly_activity':
                continue
            table, columns = COLUMNS[metric]
            if metric == 'metadata' and has_activity:
                columns += ',input_sha256'
            # Both identifiers are code constants. No request text becomes SQL.
            frame = con.execute(f'SELECT {columns} FROM main."{table}" LIMIT 501').df()
            if len(frame) > 500:
                raise ValueError('Aggregate row limit exceeded; no truncated result returned.')
            if metric == 'metadata' and len(frame) != 1:
                raise ValueError('Expected one report metadata row.')
            tables[metric] = json.loads(frame.to_json(orient='split', index=False, double_precision=15))
            tables[metric] = dict(columns=tables[metric]['columns'], rows=tables[metric]['data'])
        if has_activity:
            metadata = dict(zip(tables['metadata']['columns'],tables['metadata']['rows'][0]))
            tables['monthly_activity'], exclusions = monthly_activity(request['events_source']['path'],metadata)
            tables['metadata']['columns'].append('activity_date_exclusions_snapshot')
            tables['metadata']['rows'][0].append(json.dumps(exclusions,sort_keys=True))
    if digest(request['path']) != request['fingerprint']:
        raise ValueError('Report changed during query.')
    output = json.dumps({'tables': tables}, ensure_ascii=True, allow_nan=False)
    if len(output.encode('utf-8')) > 1024 * 1024:
        raise ValueError('Output size exceeded.')
    return output


if __name__ == '__main__':
    try:
        incoming = sys.stdin.read(16000)
        sys.stdout.write(run(json.loads(incoming)))
    except ActivitySourceError as exc:
        sys.stdout.write(json.dumps({'error':str(exc)}))
    except Exception:
        # Never forward paths, SQL internals or database contents to the UI.
        sys.stdout.write(json.dumps({'error': 'Query integrity, schema or resource check failed.'}))

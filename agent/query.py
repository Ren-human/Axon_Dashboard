"""Closed query plans executed in a disposable Python process, with hard timeout."""
import json
from pathlib import Path
import subprocess
import sys
import pandas as pd
from .context import fingerprint, event_source
from .catalog import METRICS

MAX_BYTES = 1024 * 1024
QUERY_VERSION = '2.2.0'


def execute(context, metrics, timeout=6):
    metrics = list(dict.fromkeys(metrics))
    if not metrics or len(metrics) > 6 or any(m not in METRICS for m in metrics):
        raise ValueError('Unsupported query plan.')
    if fingerprint(context.path) != context.fingerprint:
        raise ValueError('Report changed. Submit a new request.')
    request = dict(path=context.path, fingerprint=context.fingerprint, metrics=metrics)
    if 'monthly_activity' in metrics:
        request['events_source'] = event_source(context)
    payload = json.dumps(request)
    try:
        process = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('worker.py'))],
                                 input=payload, text=True, encoding='utf-8', capture_output=True,
                                 timeout=timeout, cwd=str(Path(__file__).resolve().parents[1]))
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Query timed out; worker was terminated. No result was published.') from exc
    if process.returncode or len(process.stdout.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Read-only query failed or exceeded its output limit.')
    try:
        envelope = json.loads(process.stdout)
        if envelope.get('error'):
            raise ValueError(envelope['error'])
        tables = {name: pd.DataFrame(value['rows'], columns=value['columns'])
                  for name, value in envelope['tables'].items()}
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid query result envelope.') from exc
    if fingerprint(context.path) != context.fingerprint:
        raise ValueError('Report changed during execution; results withheld.')
    return tables

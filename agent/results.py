"""Deterministic transformations of validated aggregate query results."""
from math import isfinite
import pandas as pd
from summary_validation import OUTCOME_LABELS, outcome_summary, occupancy_summary, valid_count, rate_matches
from .catalog import NOTES, STAGES, COHORTS


def selected(frame, filters):
    work = frame.copy()
    for item in filters:
        field, op, val = item['field'], item['op'], item['value']
        if field not in work:
            raise ValueError('Requested filter is unavailable.')
        if op == 'between':
            if val[0] < str(work[field].min()) or val[1] > str(work[field].max()):
                raise ValueError('Requested months are outside this report; no silent clipping.')
            work = work[work[field].between(*val)]
        else:
            values = val if isinstance(val, list) else [val]
            if any(v not in frame[field].tolist() for v in values):
                raise ValueError('Requested category is absent from this report.')
            work = work[work[field].isin(values)]
    return work


def safe_float(value):
    if pd.isna(value):
        return None
    result = float(value)
    if not isfinite(result):
        raise ValueError('Non-finite result.')
    return result


def analyze(spec, tables):
    metric, view = spec['metric'], spec['view']
    frame = tables[metric].copy()
    unit, x, y, series = 'residents', None, None, None
    if metric == 'monthly_activity':
        required = {'month','event','n'}
        if frame.empty or not required <= set(frame) or frame[['month','event']].duplicated().any():
            raise ValueError('Monthly activity aggregate structure is invalid.')
        if not set(frame['event']) <= {'referral','intake','admission'} or any(not valid_count(v) for v in frame['n']):
            raise ValueError('Monthly activity contains invalid events or counts.')
        data = selected(frame,spec['filters']).sort_values(['month','event'])
        unit, x, y, series = 'recorded events', 'month', ['n'], 'event'
    elif metric == 'occupancy':
        summary, issue = occupancy_summary(frame, tables['metadata'])
        if summary is None:
            raise ValueError(issue)
        work = selected(summary['monthly'], spec['filters'])
        if work.empty:
            raise ValueError('No months selected.')
        unit = 'fraction of available bed-days'
        if view == 'weighted_lower':
            numerator = float(work['known_bed_days_lower'].sum())
            denominator = float(work['available_bed_days'].sum())
            data = pd.DataFrame([dict(period=f"{work['period_start'].iloc[0]} – {work['period_end_inclusive'].iloc[-1]}",
                                      numerator=numerator, denominator=denominator,
                                      value=numerator / denominator if denominator else None)])
            x, y = 'period', ['value']
        else:
            data = work[['month', 'occupancy_lower', 'occupancy_upper', 'known_bed_days_lower', 'available_bed_days']]
            x, y = 'month', ['occupancy_lower', 'occupancy_upper']
    elif metric == 'outcomes':
        if len(frame) != 2 or set(frame['horizon_months']) != {6, 12}:
            raise ValueError('Expected unique 6- and 12-month outcome rows.')
        summaries = {}
        for horizon in (6, 12):
            summary, issue = outcome_summary(frame, horizon)
            if summary is None:
                raise ValueError(issue)
            summaries[horizon] = summary
        work = selected(frame, spec['filters'])
        if view == 'breakdown':
            rows = []
            for horizon in work['horizon_months']:
                summary = summaries[horizon]
                rows.extend(dict(horizon_months=horizon, outcome=OUTCOME_LABELS[k], n=v,
                                 due_n=summary['due']) for k, v in summary['counts'].items())
            data = pd.DataFrame(rows)
            x, y, series = 'outcome', ['n'], 'horizon_months'
        else:
            numerator = 'known_outcome_n' if view == 'coverage' else 'relapse_reported'
            data = work[['horizon_months', numerator, 'due_n']].copy().rename(columns={numerator: 'numerator', 'due_n': 'denominator'})
            data['value'] = [float(a) / float(b) if b else None for a, b in zip(data['numerator'], data['denominator'])]
            unit, x, y = 'fraction of all residents due', 'horizon_months', ['value']
    elif metric == 'funnel':
        if frame['stage'].tolist() != STAGES:
            raise ValueError('Invalid funnel stage order or uniqueness.')
        previous = None
        for _, row in frame.iterrows():
            if not valid_count(row['n']) or not valid_count(row['previous_stage_n']):
                raise ValueError('Invalid funnel counts.')
            if row['n'] > row['previous_stage_n'] or (previous is not None and row['previous_stage_n'] != previous):
                raise ValueError('Funnel counts do not reconcile.')
            if not rate_matches(row['conversion_from_previous'], row['n'], row['previous_stage_n']):
                raise ValueError('Funnel conversion does not reconcile.')
            if not rate_matches(row['conversion_from_referrals'], row['n'], frame.iloc[0]['n']):
                raise ValueError('Referral conversion does not reconcile.')
            previous = row['n']
        work = selected(frame, spec['filters'])
        data = work[['stage', 'n']].copy()
        x, y = 'stage', ['n']
        if view == 'conversion':
            data = work[['stage', 'n', 'previous_stage_n', 'conversion_from_previous']].copy().rename(
                columns={'n': 'numerator', 'previous_stage_n': 'denominator', 'conversion_from_previous': 'value'})
            unit, y = 'fraction of previous strict stage', ['value']
    elif metric == 'los':
        if len(frame) != 3 or set(frame['cohort']) != set(COHORTS):
            raise ValueError('Expected three unique LOS cohorts.')
        for _, row in frame.iterrows():
            if not valid_count(row['n']):
                raise ValueError('Invalid LOS count.')
            values = [safe_float(row[k]) for k in ('median_days', 'p90_days')]
            if row['n'] == 0 and any(v is not None for v in values):
                raise ValueError('Empty LOS cohort requires null statistics.')
            if row['n'] > 0 and (any(v is None or v < 0 for v in values) or values[0] > values[1]):
                raise ValueError('Invalid LOS statistics.')
        data = selected(frame, spec['filters'])
        unit, x, y = 'days (cohorts kept separate)', 'cohort', ['median_days', 'p90_days']
    else:
        if frame[['severity', 'rule']].duplicated().any() or any(not valid_count(v) for v in frame['n']):
            raise ValueError('Invalid quality aggregates.')
        data = selected(frame, spec['filters'])
        unit, x, y, series = 'rule flags, not unique residents', 'rule', ['n'], 'severity'
    if spec['output']['type'] == 'scalar' and len(data) != 1:
        if metric == 'quality':
            data = pd.DataFrame([{'n': int(data['n'].sum())}])
        else:
            raise ValueError('The request has multiple groups; use table or chart output.')
    sort = spec['output'].get('sort', 'source')
    if sort != 'source' and not data.empty:
        data = data.sort_values(y[0], ascending=sort == 'ascending', na_position='last')
    # JSON round trip eliminates NaN and numpy scalars, retaining explicit null.
    import json
    records = json.loads(data.to_json(orient='records', double_precision=15))
    return dict(metric=metric, view=view, rows=records, columns=list(data), unit=unit,
                x=x, y=y, series=series, note=NOTES[metric], spec=spec)

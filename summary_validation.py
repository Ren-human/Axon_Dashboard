"""Validate stored aggregates only; resident business calculations live in metrics.py."""
from datetime import date, timedelta
from math import isclose, isfinite

import pandas as pd

OUTCOME_LABELS = {
    'engaged_in_recovery': 'Engaged in recovery',
    'relapse_reported': 'Relapse reported',
    'lost_to_follow_up': 'Lost to follow-up',
    'unknown': 'Unknown', 'missing': 'Missing',
    'due_but_marked_not_yet_due': 'Due but marked not yet due',
    'unrecognized': 'Unrecognized',
}


def number(value):
    if isinstance(value, bool):
        return float('nan')
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return float('nan')


def valid_count(value):
    n = number(value)
    return isfinite(n) and n >= 0 and n.is_integer()


def rate_matches(stored, numerator, denominator):
    if denominator == 0:
        return stored is None or (not isinstance(stored, str) and pd.isna(stored))
    n = number(stored)
    return isfinite(n) and isclose(n, numerator / denominator, rel_tol=1e-7, abs_tol=1e-9)


def outcome_summary(frame, months):
    required = {'horizon_months', 'due_n', 'known_outcome_n', 'ascertainment_rate', *OUTCOME_LABELS}
    missing = required - set(frame)
    if missing:
        return None, 'Outcomes missing columns: ' + ', '.join(sorted(missing))
    rows = frame[pd.to_numeric(frame['horizon_months'], errors='coerce') == months]
    if len(rows) != 1:
        return None, f'Expected one {months}-month outcome row; found {len(rows)}. Metrics and chart withheld.'
    row = rows.iloc[0]
    count_cols = ['due_n', 'known_outcome_n', *OUTCOME_LABELS]
    count_cols += [c for c in ('cohort_n', 'not_due', 'eligibility_unknown', 'outside_cohort',
                              'unresolved_due_n') if c in row.index]
    if any(not valid_count(row[c]) for c in count_cols):
        return None, 'Outcome counts must be finite, non-negative whole numbers. Metrics and chart withheld.'
    due, known = number(row['due_n']), number(row['known_outcome_n'])
    counts = {c: number(row[c]) for c in OUTCOME_LABELS}
    if known > due or known != counts['engaged_in_recovery'] + counts['relapse_reported']:
        return None, 'known_outcome_n must equal engaged_in_recovery + relapse_reported and be ≤ due_n. Metrics and chart withheld.'
    if sum(counts.values()) != due:
        return None, 'The seven outcome categories do not sum to due_n. Metrics and chart withheld.'
    if 'unresolved_due_n' in row.index and number(row['unresolved_due_n']) != due - known:
        return None, 'unresolved_due_n is inconsistent. Metrics and chart withheld.'
    if all(c in row.index for c in ('cohort_n', 'not_due', 'eligibility_unknown')):
        if number(row['cohort_n']) != due + number(row['not_due']) + number(row['eligibility_unknown']):
            return None, 'Follow-up cohort counts do not reconcile. Metrics and chart withheld.'
    expected_rates = {
        'ascertainment_rate': known,
        'recovery_fraction_all_due_lower': counts['engaged_in_recovery'],
        'recovery_fraction_all_due_upper': counts['engaged_in_recovery'] + due - known,
        'relapse_fraction_all_due': counts['relapse_reported'],
        'ltfu_rate_all_due': counts['lost_to_follow_up'],
        'unresolved_rate_all_due': due - known,
    }
    for col, numerator in expected_rates.items():
        if col in row.index and not rate_matches(row[col], numerator, due):
            return None, f'{col} does not match the stored counts (zero denominator requires null). Metrics and chart withheld.'
    return {'due': due, 'known': known, 'coverage': known / due if due else float('nan'),
            'counts': counts, 'row': row}, ''


def occupancy_summary(frame, metadata):
    """Require complete, contiguous coverage of the metadata reporting window."""
    required = {'month', 'period_start', 'period_end_inclusive', 'observed_days',
                'available_bed_days', 'known_bed_days_lower', 'bed_days_upper',
                'occupancy_lower', 'occupancy_upper'}
    if frame.empty or not required <= set(frame):
        return None, 'Report-period occupancy unavailable: missing rows or bed-day/period columns.'
    try:
        if len(metadata) != 1:
            raise ValueError('one metadata row required')
        meta = metadata.iloc[0]
        start, end = date.fromisoformat(str(meta['occupancy_start'])), date.fromisoformat(str(meta['as_of']))
        if start > end:
            raise ValueError('invalid reporting window')
        capacity = number(meta['bed_capacity'])
        if not valid_count(capacity) or capacity <= 0:
            raise ValueError('invalid report capacity')
        work = frame.copy().sort_values('month')
        expected_start = start
        for _, r in work.iterrows():
            a = date.fromisoformat(str(r['period_start']))
            b = date.fromisoformat(str(r['period_end_inclusive']))
            if a != expected_start or b < a or b > end:
                raise ValueError('missing, overlapping or out-of-period months')
            next_month = date(a.year + (a.month == 12), a.month % 12 + 1, 1)
            if b != min(end, next_month - timedelta(days=1)) or str(r['month']) != a.strftime('%Y-%m'):
                raise ValueError('invalid monthly coverage')
            if any(not valid_count(r[c]) for c in ('observed_days', 'available_bed_days',
                                                   'known_bed_days_lower', 'bed_days_upper')):
                raise ValueError('invalid bed-day counts')
            days, available = number(r['observed_days']), number(r['available_bed_days'])
            lower, upper = number(r['known_bed_days_lower']), number(r['bed_days_upper'])
            if days != (b - a).days + 1 or upper < lower:
                raise ValueError('invalid days or occupancy bounds')
            # A zero denominator remains explicitly undefined, never a 0% rate.
            if available and available != capacity * days:
                raise ValueError('available bed-days do not match capacity × observed days')
            if available == 0 and (lower or upper):
                raise ValueError('occupied bed-days with zero available bed-days')
            if not rate_matches(r['occupancy_lower'], lower, available) or not rate_matches(r['occupancy_upper'], upper, available):
                raise ValueError('stored monthly rates do not match bed-days')
            if 'uncertain_bed_days' in r.index:
                if not valid_count(r['uncertain_bed_days']) or lower + number(r['uncertain_bed_days']) != upper:
                    raise ValueError('uncertain bed-days do not reconcile')
            expected_start = b + timedelta(days=1)
        if expected_start != end + timedelta(days=1):
            raise ValueError('reporting months are incomplete')
        available = sum(number(x) for x in work['available_bed_days'])
        if (work['available_bed_days'].map(number) == 0).any() and available:
            raise ValueError('a month has no available bed-days; full-period rate withheld')
        known = sum(number(x) for x in work['known_bed_days_lower'])
        return {'rate': known / available if available else float('nan'), 'start': start,
                'end': end, 'monthly': work, 'available': available}, ''
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        return None, f'Report-period occupancy unavailable: {exc}. No months silently excluded.'

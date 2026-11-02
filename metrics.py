"""Axon Health Task A, tailored to harbourview_residents.csv (stdlib only).

Run: python metrics.py harbourview_residents.csv --as-of 2026-01-15 --out outputs
See README.md for definitions and limitations. No dates or outcomes are imputed.
"""
from __future__ import annotations

import argparse
import calendar
import collections
import csv
from datetime import date, datetime, timedelta
import hashlib
import html
import io
import json
import math
from numbers import Real
import sys
from pathlib import Path

METRICS_VERSION = '1.0.1'

DATE_COLS = ('referral_date', 'intake_date', 'admission_date', 'discharge_date')
REQUIRED = ('resident_id', *DATE_COLS, 'current_status', 'discharge_reason',
            'entrance_fee', 'fee_waived', 'followup_6m', 'followup_12m',
            'staff_note', 'bed_capacity')
ACTIVE = {'phase_1', 'phase_2', 'phase_3'}
EXITED = {'discharged', 'alumni', 'aftercare'}
OUTCOMES = {'engaged_in_recovery', 'relapse_reported', 'lost_to_follow_up',
            'unknown', 'not_yet_due', ''}


def parse_date(value):
    if not value:
        return None
    for fmt in ('%m/%d/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f'Invalid date: {value!r}; expected M/D/YYYY or YYYY-MM-DD')


def add_months(d, months):
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def ratio(n, d):
    return n / d if d else None


def percentile(values, p):
    """Linear interpolation, equivalent to numpy's default percentile method."""
    if not values:
        return None
    a = sorted(values)
    x = (len(a) - 1) * p
    lo = int(x)
    hi = min(lo + 1, len(a) - 1)
    return a[lo] + (a[hi] - a[lo]) * (x - lo)


def stats(values):
    return {'n': len(values), 'median_days': percentile(values, .5),
            'p90_days': percentile(values, .9),
            'min_days': min(values) if values else None,
            'max_days': max(values) if values else None}


def load_data(path):
    return _load_csv_bytes(Path(path).read_bytes())


def _load_csv_bytes(source_bytes):
    # Parsing and provenance use the same bytes, even if the source later changes.
    with io.StringIO(source_bytes.decode('utf-8-sig'), newline='') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        missing = set(REQUIRED) - set(headers)
        if missing or len(headers) != len(set(headers)):
            raise ValueError(f'Missing columns: {sorted(missing)}; duplicate headers prohibited')
        rows = []
        for line, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f'Malformed CSV record at line {line}')
            rows.append({**{k: v.strip() for k, v in row.items()}, '_row': line})
    if not rows:
        raise ValueError('CSV contains no data rows')
    return rows, headers


def calculate(raw, as_of, capacity=None, anchor='discharge', start=None, fiscal_year=None):
    if type(as_of) is not date:
        raise ValueError('as_of must be a datetime.date')
    if start is not None and type(start) is not date:
        raise ValueError('Occupancy start must be a datetime.date')
    if fiscal_year is not None and (type(fiscal_year) is not int or not 1 <= fiscal_year <= 9999):
        raise ValueError('Fiscal year must be an integer from 1 to 9999')
    if anchor not in ('discharge', 'admission'):
        raise ValueError('Follow-up anchor must be discharge or admission')
    if capacity is not None:
        try:
            valid_capacity = (not isinstance(capacity, bool) and isinstance(capacity, Real)
                              and math.isfinite(capacity) and capacity > 0
                              and capacity == int(capacity))
        except (ValueError, OverflowError):
            valid_capacity = False
        if not valid_capacity:
            raise ValueError('Capacity must be a finite positive integer')
        capacity = int(capacity)
    snapshot = as_of
    fiscal_start = date(fiscal_year, 1, 1) if fiscal_year else None
    if fiscal_year:
        as_of = min(snapshot, date(fiscal_year, 12, 31))
        if as_of < fiscal_start:
            raise ValueError('Snapshot predates requested fiscal year')
    issues = []

    def flag(r, rule, severity, explanation):
        issues.append({'source_row': r['_row'], 'resident_id': r['resident_id'],
                       'rule': rule, 'severity': severity, 'explanation': explanation})

    ids = collections.Counter(r['resident_id'] for r in raw)
    rows = []
    for source in raw:
        r = dict(source)
        if not r['resident_id'] or ids[r['resident_id']] > 1:
            flag(r, 'MISSING_ID' if not r['resident_id'] else 'DUPLICATE_ID', 'HIGH',
                 'Excluded from all metrics; duplicate residents require explicit resolution')
            continue
        for c in DATE_COLS:
            try:
                r[c] = parse_date(source[c])
            except ValueError:
                r[c] = None
                flag(r, 'INVALID_' + c.upper(), 'HIGH', 'Invalid date treated as unavailable')
            if r[c] and r[c] > as_of:
                flag(r, 'FUTURE_' + c.upper(), 'REVIEW', 'Event is after reporting cutoff')
        for c in ('current_status', 'discharge_reason', 'followup_6m', 'followup_12m', 'fee_waived'):
            r[c] = r[c].lower()
        status = r['current_status']
        if status not in ACTIVE | EXITED | {'not_admitted'}:
            flag(r, 'UNKNOWN_STATUS', 'HIGH', 'Status cannot establish open or closed stay')
        for a, b, rule in [
            ('referral_date', 'intake_date', 'NEGATIVE_REFERRAL_TO_INTAKE'),
            ('intake_date', 'admission_date', 'NEGATIVE_INTAKE_TO_ADMISSION'),
            ('referral_date', 'admission_date', 'NEGATIVE_REFERRAL_TO_ADMISSION'),
            ('admission_date', 'discharge_date', 'NEGATIVE_LENGTH_OF_STAY')]:
            if r[a] and r[b] and r[b] < r[a]:
                flag(r, rule, 'HIGH', f'{b} precedes {a}; affected duration excluded')
        for later, earlier in [('intake_date', 'referral_date'),
                               ('admission_date', 'referral_date'),
                               ('admission_date', 'intake_date'),
                               ('discharge_date', 'admission_date')]:
            if r[later] and not r[earlier]:
                flag(r, 'MISSING_' + earlier.replace('_date', '').upper(), 'MEDIUM',
                     f'{later} exists without {earlier}; no milestone imputation')
        if status in EXITED and not r['discharge_date']:
            flag(r, 'MISSING_DISCHARGE_DATE', 'HIGH', 'Exited status without usable exit date')
        if r['discharge_date'] and not r['discharge_reason']:
            flag(r, 'MISSING_DISCHARGE_REASON', 'MEDIUM', 'Exit exists without reason')
        if r['discharge_date'] and status not in EXITED:
            flag(r, 'STATUS_DISCHARGE_CONFLICT', 'HIGH', 'Dated exit takes precedence for stay interval')
        if status == 'not_admitted' and r['admission_date']:
            flag(r, 'STATUS_ADMISSION_CONFLICT', 'HIGH', 'Admission exists for not_admitted status')
        if status in ACTIVE | EXITED and not r['admission_date']:
            flag(r, 'MISSING_ADMISSION_DATE', 'HIGH', 'Status implies admission but date is unavailable')
        fee = None
        if r['entrance_fee']:
            try:
                fee = float(r['entrance_fee'])
                if not math.isfinite(fee) or fee < 0:
                    raise ValueError
            except ValueError:
                flag(r, 'INVALID_ENTRANCE_FEE', 'MEDIUM', 'Fee must be finite and nonnegative')
                fee = None
        if r['fee_waived'] not in ('', 'true', 'false'):
            flag(r, 'INVALID_FEE_WAIVED', 'MEDIUM', 'Expected TRUE, FALSE or blank')
        if r['fee_waived'] == 'true' and fee is not None and fee > 0:
            flag(r, 'WAIVED_WITH_POSITIVE_FEE', 'REVIEW', 'Waiver conflicts with positive fee')
        if r['fee_waived'] == 'false' and fee == 0:
            flag(r, 'NOT_WAIVED_ZERO_FEE', 'REVIEW', 'Zero fee without waiver')
        for horizon in (6, 12):
            if r[f'followup_{horizon}m'] not in OUTCOMES:
                flag(r, f'INVALID_FOLLOWUP_{horizon}M', 'MEDIUM', 'Unrecognized follow-up category')
        rows.append(r)

    capacities = set()
    capacity_bad = False
    for r in raw:
        try:
            value = float(r['bed_capacity'])
            if not value.is_integer() or value <= 0:
                raise ValueError
            capacities.add(int(value))
        except ValueError:
            capacity_bad = True
            flag(r, 'INVALID_BED_CAPACITY', 'HIGH', 'Positive integer bed capacity required')
    if capacity is None:
        if capacity_bad or len(capacities) != 1:
            raise ValueError('Capacity missing/variable: supply --capacity after confirming capacity history')
        capacity = next(iter(capacities))
    if capacity <= 0:
        raise ValueError('Capacity must be positive')

    def occurred(r, c):
        return r[c] is not None and r[c] <= as_of

    # Referral-year cohort for funnel/stages; all history for census/LOS/follow-up.
    funnel_rows = [r for r in rows if not fiscal_start or
                   (occurred(r, 'referral_date') and r['referral_date'] >= fiscal_start)]
    observed = {c: sum(occurred(r, c) for r in funnel_rows) for c in DATE_COLS}
    referral = [r for r in funnel_rows if occurred(r, 'referral_date')]
    intake = [r for r in referral if occurred(r, 'intake_date') and r['intake_date'] >= r['referral_date']]
    admitted = [r for r in intake if occurred(r, 'admission_date') and r['admission_date'] >= r['intake_date']]
    closed = [r for r in admitted if occurred(r, 'discharge_date') and r['discharge_date'] >= r['admission_date']]
    funnel = []
    previous = len(funnel_rows)
    for name, cohort in [('referral', referral), ('intake', intake), ('admission', admitted), ('discharge', closed)]:
        funnel.append({'stage': name, 'n': len(cohort), 'previous_stage_n': previous,
                       'conversion_from_previous': ratio(len(cohort), previous),
                       'conversion_from_referrals': ratio(len(cohort), len(referral))})
        previous = len(cohort)

    stages, stage_unresolved = [], []
    for a, b in [('referral_date', 'intake_date'), ('intake_date', 'admission_date'),
                 ('referral_date', 'admission_date'), ('admission_date', 'discharge_date')]:
        values, exclusions = [], collections.Counter()
        for r in funnel_rows:
            if not r[a] or not r[b]:
                exclusions['missing_or_invalid_endpoint'] += 1
            elif r[a] > as_of or r[b] > as_of:
                exclusions['endpoint_after_cutoff'] += 1
            elif r[b] < r[a]:
                exclusions['negative_duration'] += 1
            else:
                values.append((r[b] - r[a]).days)
        stages.append({'stage': f'{a.removesuffix("_date")}_to_{b.removesuffix("_date")}',
                       'total_records': len(funnel_rows), **stats(values), **{
                           k: exclusions[k] for k in ('missing_or_invalid_endpoint', 'endpoint_after_cutoff', 'negative_duration')}})
        waiting = [r for r in funnel_rows if occurred(r, a) and not occurred(r, b)]
        stage_unresolved.append({'stage': stages[-1]['stage'],
                                  'start_observed_n': sum(occurred(r, a) for r in funnel_rows),
                                  'no_next_milestone_by_cutoff_n': len(waiting),
                                  **{'elapsed_' + k: v for k, v in stats([(as_of-r[a]).days for r in waiting]).items()}})

    stays, completed, ongoing, program_completed = [], [], [], []
    los_exclusions = collections.Counter()
    resident_metrics = []
    for r in rows:
        a, d = r['admission_date'], r['discharge_date']
        kind, days = None, None
        if not a or a > as_of:
            los_exclusions['no_admission_by_cutoff'] += 1
        elif d and d < a:
            los_exclusions['negative_los'] += 1
        elif d and d <= as_of:
            kind, days = 'ended', (d - a).days
            if not fiscal_start or d >= fiscal_start:
                completed.append(days)
                if r['discharge_reason'] == 'completed':
                    program_completed.append(days)
            else:
                los_exclusions['ended_before_fiscal_year'] += 1
            stays.append((a, d, False))
        elif d and d > as_of:
            # A known later exit demonstrates that the resident was present at cutoff.
            kind, days = 'ongoing', (as_of - a).days
            ongoing.append(days)
            stays.append((a, as_of + timedelta(days=1), False))
        elif r['current_status'] in ACTIVE:
            kind, days = 'ongoing', (as_of - a).days
            ongoing.append(days)
            stays.append((a, as_of + timedelta(days=1), False))
        else:
            kind = 'unknown_exit'
            los_exclusions['unknown_exit'] += 1
            stays.append((a, as_of + timedelta(days=1), True))
        resident_metrics.append({'resident_id': r['resident_id'], 'source_row': r['_row'],
                                 'los_category': kind or 'excluded', 'los_days': days})
    los = {'ended_stays': stats(completed), 'ongoing_elapsed_stays': stats(ongoing),
           'program_completed_subset': stats(program_completed), 'exclusions': dict(los_exclusions)}

    first = start or fiscal_start or (min(a for a, _, _ in stays) if stays else as_of.replace(day=1))
    if first > as_of:
        raise ValueError('Occupancy start must be on or before cutoff')
    occupancy = []
    month = first.replace(day=1)
    while month <= as_of:
        next_month = add_months(month, 1)
        lo, hi = max(month, first), min(next_month, as_of + timedelta(days=1))
        days = (hi - lo).days
        known = uncertain = 0
        for a, d, unknown in stays:
            overlap = max(0, (min(d, hi) - max(a, lo)).days)
            if unknown:
                uncertain += overlap
            else:
                known += overlap
        census_day = hi - timedelta(days=1)
        known_census = sum(a <= census_day < d for a, d, u in stays if not u)
        uncertain_census = sum(a <= census_day < d for a, d, u in stays if u)
        denominator = capacity * days
        occupancy.append({'month': month.strftime('%Y-%m'), 'period_start': lo.isoformat(),
                          'period_end_inclusive': census_day.isoformat(), 'observed_days': days,
                          'bed_capacity': capacity, 'available_bed_days': denominator,
                          'known_bed_days_lower': known, 'uncertain_bed_days': uncertain,
                          'bed_days_upper': known + uncertain,
                          'occupancy_lower': ratio(known, denominator),
                          'occupancy_upper': ratio(known + uncertain, denominator),
                          'average_census_lower': ratio(known, days),
                          'average_census_upper': ratio(known + uncertain, days),
                          'period_end_census_lower': known_census,
                          'period_end_census_upper': known_census + uncertain_census,
                          'lower_exceeds_capacity': known > denominator,
                          'upper_exceeds_capacity': known + uncertain > denominator})
        month = next_month

    outcomes, followup_detail = [], []
    for horizon in (6, 12):
        buckets = collections.Counter()
        for r in rows:
            a, d = r['admission_date'], r['discharge_date']
            # Snapshot status must not pull a known future exit into a historical cohort.
            exited = bool(d and d <= as_of) or (not d and r['current_status'] in EXITED)
            if anchor == 'discharge' and not exited:
                buckets['outside_cohort'] += 1
                continue
            if anchor == 'admission' and not (a and a <= as_of):
                buckets['outside_cohort'] += 1
                continue
            base = d if anchor == 'discharge' else a
            invalid = (not base or not a or (d and d < a) or a > as_of or base > as_of)
            value = r[f'followup_{horizon}m']
            if invalid:
                bucket, due = 'eligibility_unknown', None
            else:
                due = add_months(base, horizon)
                if due > as_of:
                    bucket = 'not_due'
                    if value not in ('', 'not_yet_due'):
                        flag(r, f'OUTCOME_BEFORE_DUE_{horizon}M', 'REVIEW',
                             'Recorded outcome before calculated due date; excluded from mature cohort')
                elif value in ('engaged_in_recovery', 'relapse_reported', 'lost_to_follow_up', 'unknown'):
                    bucket = value
                elif value == 'not_yet_due':
                    bucket = 'due_but_marked_not_yet_due'
                    flag(r, f'DUE_BUT_NOT_YET_DUE_{horizon}M', 'MEDIUM',
                         'Mature resident marked not_yet_due; retained in due denominator')
                elif value == '':
                    bucket = 'missing'
                else:
                    bucket = 'unrecognized'
            buckets[bucket] += 1
            followup_detail.append({'resident_id': r['resident_id'], 'horizon_months': horizon,
                                    'anchor_date': base.isoformat() if base else None,
                                    'due_date': due.isoformat() if due else None,
                                    'recorded_value': value, 'analysis_bucket': bucket})
        due_n = sum(buckets[k] for k in ('engaged_in_recovery', 'relapse_reported',
                    'lost_to_follow_up', 'unknown', 'missing', 'due_but_marked_not_yet_due', 'unrecognized'))
        recovery, relapse, ltfu = (buckets[k] for k in ('engaged_in_recovery', 'relapse_reported', 'lost_to_follow_up'))
        observed_n = recovery + relapse
        unresolved = due_n - observed_n
        outcomes.append({'horizon_months': horizon, 'anchor': anchor,
                         'cohort_n': len(rows) - buckets['outside_cohort'],
                         'outside_cohort': buckets['outside_cohort'],
                         'eligibility_unknown': buckets['eligibility_unknown'], 'not_due': buckets['not_due'],
                         'due_n': due_n, **{k: buckets[k] for k in ('engaged_in_recovery',
                          'relapse_reported', 'lost_to_follow_up', 'unknown', 'missing',
                          'due_but_marked_not_yet_due', 'unrecognized')},
                         'known_outcome_n': observed_n, 'unresolved_due_n': unresolved,
                         'ascertainment_rate': ratio(observed_n, due_n),
                         'recovery_fraction_all_due_lower': ratio(recovery, due_n),
                         'recovery_fraction_all_due_upper': ratio(recovery + unresolved, due_n),
                         'relapse_fraction_all_due': ratio(relapse, due_n),
                         'ltfu_rate_all_due': ratio(ltfu, due_n),
                         'unresolved_rate_all_due': ratio(unresolved, due_n)})

    quality_counts = collections.Counter((x['severity'], x['rule']) for x in issues)
    quality = [{'severity': s, 'rule': r, 'n': n} for (s, r), n in sorted(quality_counts.items())]
    metadata = {'as_of': as_of.isoformat(), 'snapshot_as_of': snapshot.isoformat(),
                'fiscal_year': fiscal_year, 'funnel_cohort_n': len(funnel_rows),
                'followup_cohort': (
                    'All historical exits by reporting cutoff, maturity assessed at cutoff'
                    if anchor == 'discharge' else
                    'All historical admissions by reporting cutoff, maturity assessed at cutoff'),
                'followup_anchor': anchor, 'input_rows': len(raw),
                'included_unique_residents': len(rows), 'excluded_identity_rows': len(raw) - len(rows),
                'bed_capacity': capacity, 'source_capacity_values': sorted(capacities),
                'occupancy_start': first.isoformat(), 'issue_count': len(issues),
                'residents_with_issues': len({x['resident_id'] for x in issues})}
    return {'metadata': metadata, 'observed_milestones': observed, 'funnel': funnel,
            'stage_durations': stages, 'stage_unresolved': stage_unresolved,
            'los': los, 'monthly_occupancy': occupancy,
            'outcomes': outcomes, 'data_quality_summary': quality,
            'data_quality_issues': issues, 'resident_metrics': resident_metrics,
            'followup_detail': followup_detail}


def write_csv(path, records, empty_headers=()):
    headers = list(records[0]) if records else list(empty_headers)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(records)


def dashboard(result):
    """Portable offline dashboard; the underlying report supplies every denominator."""
    m = result['metadata']
    def esc(x):
        if isinstance(x, float):
            x = f'{x:.2f}'.rstrip('0').rstrip('.')
        return html.escape(str(x))
    def pct(x):
        return 'NA' if x is None else f'{100*x:.1f}%'
    def table(headers, records):
        return '<table><thead><tr>' + ''.join(f'<th>{esc(h)}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join(
            '<tr>' + ''.join(f'<td>{esc(v)}</td>' for v in row) + '</tr>' for row in records) + '</tbody></table>'
    body = f'<header><span>AXON HEALTH / HARBOURVIEW</span><h1>House performance</h1><p>Fiscal year: {esc(m["fiscal_year"] or "All history")} · Cutoff: {m["as_of"]} · Capacity: {m["bed_capacity"]} beds</p></header>'
    body += '<aside>Snapshot date ' + esc(m['snapshot_as_of']) + ' is a reporting assumption, not confirmed source metadata. Follow-up is measured from ' + esc(m['followup_anchor']) + '. No assessment dates are supplied. All outcome rates below use everyone due.</aside>'
    body += '<section><h2>Referral funnel</h2><p>Referral-year cohort; only ordered, observed milestones count. Incomplete stages stay outside completed-duration summaries.</p>'
    body += table(['Stage', 'Count / previous stage', 'Conversion'], [
        [r['stage'], f"{r['n']} / {r['previous_stage_n']}", pct(r['conversion_from_previous'])] for r in result['funnel']])
    body += '<p>Observed dates (independent of missing intermediate stages): ' + esc(json.dumps(result['observed_milestones'])) + '.</p>'
    body += table(['Stage', 'Valid N', 'Median days', 'P90 days'], [[r['stage'], r['n'], r['median_days'], r['p90_days']] for r in result['stage_durations']])
    body += table(['Unresolved stage', 'No next milestone / start observed', 'Median elapsed days'], [[r['stage'], f"{r['no_next_milestone_by_cutoff_n']} / {r['start_observed_n']}", r['elapsed_median_days']] for r in result['stage_unresolved']])
    body += '<p>Unresolved includes closed referrals and missing records; it is not an active waitlist count.</p></section>'
    body += '<section><h2>Monthly occupancy</h2><p>Known bed-days / available bed-days. Orange adds possible occupancy from unknown exits; upper bounds may exceed capacity. Discharge day is excluded.</p>'
    chart_max = max(1.25, max((r['occupancy_upper'] or 0 for r in result['monthly_occupancy']), default=0))
    for r in result['monthly_occupancy']:
        low, high = r['occupancy_lower'] or 0, r['occupancy_upper'] or 0
        body += f'<div class="barrow"><b>{r["month"]}</b><div class="track"><div class="known" style="width:{100*low/chart_max:.3f}%"></div><div class="uncertain" style="width:{100*(high-low)/chart_max:.3f}%"></div></div><span>{pct(low)}–{pct(high)}</span></div>'
    body += table(['Month', 'Days', 'Known / available bed-days', 'Possible extra bed-days', 'Lower', 'Upper'], [[r['month'], r['observed_days'], f"{r['known_bed_days_lower']} / {r['available_bed_days']}", r['uncertain_bed_days'], pct(r['occupancy_lower']), pct(r['occupancy_upper'])] for r in result['monthly_occupancy']])
    body += '<p>Bounds cover usable admissions. Missing admissions and excluded IDs are outside these bounds. No opening resident register is supplied; completeness of historical occupancy cannot be established.</p></section>'
    body += '<section><h2>Length of stay</h2><p>Ended stays: exits during fiscal year. Ongoing: elapsed days at cutoff, right censored; kept separate from ended LOS.</p>'
    body += table(['Cohort', 'N', 'Median days', 'P90 days'], [[k, result['los'][k]['n'], result['los'][k]['median_days'], result['los'][k]['p90_days']] for k in ('ended_stays', 'ongoing_elapsed_stays', 'program_completed_subset')])
    body += '<p>Exclusions: ' + esc(json.dumps(result['los']['exclusions'])) + '.</p></section>'
    body += '<section><h2>Funder outcomes</h2><p>' + esc(m['followup_cohort']) + '. Due dates use calendar months. Engagement is not a verified sobriety measure. Unknown eligibility is excluded from the due denominator and shown separately.</p>'
    for r in result['outcomes']:
        n = r['due_n']
        body += f'<h3>{r["horizon_months"]}-month follow-up</h3><p>Due: {n}; not due: {r["not_due"]}; eligibility unknown: {r["eligibility_unknown"]}; eligible cohort: {r["cohort_n"]}.</p>'
        categories = [(k, r[k]) for k in ('engaged_in_recovery', 'relapse_reported', 'lost_to_follow_up', 'unknown', 'missing', 'due_but_marked_not_yet_due', 'unrecognized')]
        body += table(['Category', 'Count / all due', 'Rate'], [[k or 'blank', f'{v} / {n}', pct(ratio(v,n))] for k,v in categories])
        body += f'<p><b>Worst case recovery:</b> {r["engaged_in_recovery"]} / {n} = {pct(r["recovery_fraction_all_due_lower"])}. <b>Best case recovery:</b> ({r["engaged_in_recovery"]} + {r["unresolved_due_n"]}) / {n} = {pct(r["recovery_fraction_all_due_upper"])}.</p>'
        body += '<p>Worst case treats all unresolved outcomes as not engaged; best case treats all as engaged. These are sensitivity bounds, not confidence intervals.</p>'
    body += '</section><section><h2>Data quality</h2><p>' + esc(m['issue_count']) + ' flags across ' + esc(m['residents_with_issues']) + ' resident IDs. See the issue CSV for affected residents.</p>'
    body += table(['Severity', 'Rule', 'Flags'], [[r['severity'], r['rule'], r['n']] for r in result['data_quality_summary']]) + '</section>'
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Axon Health — House performance</title><style>body{font:15px/1.6 system-ui,sans-serif;background:#eef3f5;color:#163345;margin:0 auto;max-width:1140px;padding:28px}header{background:#12364a;color:white;padding:30px;border-radius:14px}h1{font-size:38px;line-height:1.15}header span{letter-spacing:2px;font-size:12px}section,aside{background:white;padding:24px;margin-top:20px;border-radius:12px;overflow:auto}aside{border-left:5px solid #d99b42}h2{color:#174e64;margin-top:0}p{color:#48606e}table{width:100%;border-collapse:collapse;font-size:13px;margin:18px 0}th{text-align:left;background:#e7f0f3}td,th{padding:10px;border-bottom:1px solid #dde6ea}td:not(:first-child){font-variant-numeric:tabular-nums}.barrow{display:grid;grid-template-columns:75px 1fr 140px;gap:12px;align-items:center;margin:9px 0;font-size:13px}.track{display:flex;height:14px;background:#edf1f4;border-radius:4px;overflow:hidden}.known{background:#24718a}.uncertain{background:#dfac51}@media(max-width:650px){body{padding:10px}.barrow{grid-template-columns:65px 1fr 100px;gap:6px}section{padding:14px}}@media print{body{background:white}section{break-inside:avoid}header{color:#163345;background:white}}</style>' + body + '</html>'


def report(result):
    m = result['metadata']
    lines = ['# Axon Health Task A — computed results', '',
             f"Fiscal year: {m['fiscal_year'] or 'all history'}; reporting cutoff: {m['as_of']}; "
             f"snapshot assumption: {m['snapshot_as_of']}; follow-up anchor: {m['followup_anchor']}.",
             f"Input: {m['input_rows']} rows; included: {m['included_unique_residents']} unique residents; "
             f"identity exclusions: {m['excluded_identity_rows']}; capacity: {m['bed_capacity']}.", '',
             '## Observed milestones and ordered funnel', '',
             'Observed dates by cutoff: ' + json.dumps(result['observed_milestones']) + '.', '',
             '| Ordered stage | N | Previous denominator | Conversion |', '|---|---:|---:|---:|']

    def pct(x):
        return 'NA' if x is None else f'{100*x:.2f}%'

    def number(x):
        return 'NA' if x is None else f'{x:.2f}'

    for r in result['funnel']:
        lines.append(f"| {r['stage']} | {r['n']} | {r['previous_stage_n']} | {pct(r['conversion_from_previous'])} |")
    lines += ['', '## Stage durations', '', '| Stage | Valid N | Median days | P90 days |', '|---|---:|---:|---:|']
    for r in result['stage_durations']:
        lines.append(f"| {r['stage']} | {r['n']} | {number(r['median_days'])} | {number(r['p90_days'])} |")
    lines += ['', 'Next milestone not recorded by cutoff (may include closed referrals, not necessarily active waitlists):', '',
              '| Stage | Start observed | No next milestone | Median elapsed days | P90 elapsed days |',
              '|---|---:|---:|---:|---:|']
    for r in result['stage_unresolved']:
        lines.append(f"| {r['stage']} | {r['start_observed_n']} | {r['no_next_milestone_by_cutoff_n']} | "
                     f"{number(r['elapsed_median_days'])} | {number(r['elapsed_p90_days'])} |")
    lines += ['', '## Length of stay', '', '| Cohort | N | Median days | P90 days |', '|---|---:|---:|---:|']
    for k in ('ended_stays', 'ongoing_elapsed_stays', 'program_completed_subset'):
        r = result['los'][k]
        lines.append(f"| {k} | {r['n']} | {number(r['median_days'])} | {number(r['p90_days'])} |")
    lines += ['', 'LOS exclusions: ' + json.dumps(result['los']['exclusions']) + '.', '',
              '## Monthly occupancy', '',
              '| Month | Days | Available bed-days | Known bed-days | Uncertain bed-days | Lower | Upper | End census range |',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in result['monthly_occupancy']:
        lines.append(f"| {r['month']} | {r['observed_days']} | {r['available_bed_days']} | "
                     f"{r['known_bed_days_lower']} | {r['uncertain_bed_days']} | {pct(r['occupancy_lower'])} | "
                     f"{pct(r['occupancy_upper'])} | {r['period_end_census_lower']}–{r['period_end_census_upper']} |")
    lines += ['', '## Follow-up outcomes', '',
              'Cohort: ' + m['followup_cohort'] + '; only mature follow-ups enter the due denominator.', '',
              '| Months | Cohort | Eligibility unknown | Not due | Due denominator | Recovery | Relapse | LTFU | Other unresolved | Recovery lower (recovery/due) | Recovery upper ((recovery+unresolved)/due) |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in result['outcomes']:
        other = r['unresolved_due_n'] - r['lost_to_follow_up']
        lines.append(f"| {r['horizon_months']} | {r['cohort_n']} | {r['eligibility_unknown']} | {r['not_due']} | "
                     f"{r['due_n']} | {r['engaged_in_recovery']} | {r['relapse_reported']} | {r['lost_to_follow_up']} | "
                     f"{other} | {pct(r['recovery_fraction_all_due_lower'])} | "
                     f"{pct(r['recovery_fraction_all_due_upper'])} |")
    lines += ['', '## Data quality', '',
              f"{m['issue_count']} flags across {m['residents_with_issues']} resident IDs.", '',
              '| Severity | Rule | Flags |', '|---|---|---:|']
    for r in result['data_quality_summary']:
        lines.append(f"| {r['severity']} | {r['rule']} | {r['n']} |")
    lines += ['', '## Interpretation', '',
              '- Cutoff and follow-up anchor are explicit analytical assumptions; confirm against Task A.',
              '- Sequential funnel requires present, ordered intermediate dates; observed milestones also shown.',
              '- Occupancy uses [admission, discharge), excludes discharge day, and is bounded for unknown exits.',
              '- Fiscal-year occupancy includes all calendar days from January 1; final month is partial for an incomplete year.',
              '- Funnel and stage durations use referral-year cohorts. Later milestones after year end are censored.',
              '- Missing next milestones are shown as unresolved; the file cannot distinguish active waiting from closed referrals at year end.',
              '- Ended LOS includes exits in the selected fiscal year; ongoing LOS includes all known active stays at cutoff.',
              '- Bounds apply to usable admission records; missing admissions and identity exclusions are outside them.',
              '- Ongoing LOS is elapsed time at cutoff, not an estimate of eventual total LOS.',
              '- Outcomes cover all exited residents, including non-completers, unless admission anchor selected.',
              '- Unknown eligibility is separate from not due. LTFU, unknown, blank, and overdue not_yet_due remain in the due denominator.',
              '- Recovery means recorded engaged_in_recovery. Follow-up assessment dates are absent; timing cannot be verified.',
              '- Outcome bounds are worst/best case bounds for unresolved due outcomes, not confidence intervals.',
              '- Rates are fractions in CSV/JSON; null/blank denotes undefined, never zero.', '']
    return '\n'.join(lines)


def calculate_file(input_path, as_of, capacity=None, anchor='discharge', start=None, fiscal_year=None):
    """File-based calculation with provenance; use this entry point for integrations.

    calculate() remains the pure, in-memory API and cannot infer file provenance.
    This function reads the input exactly once and does not write any files.
    """
    input_path = Path(input_path)
    source_bytes = input_path.read_bytes()
    rows, headers = _load_csv_bytes(source_bytes)
    result = calculate(rows, as_of, capacity, anchor, start, fiscal_year)
    result['metadata'].update({
        'input_file': input_path.name,
        'input_sha256': hashlib.sha256(source_bytes).hexdigest(),
        'input_columns': headers,
        'capacity_overridden': capacity is not None,
        'metrics_version': METRICS_VERSION,
    })
    return result


def export_result(result, output_path):
    """Export the same aggregate files for CLI and programmatic callers.

    The caller owns staging/version publication; this function writes to its
    explicitly supplied output directory and does not activate a report.
    """
    output_path = Path(output_path)
    serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / 'metrics.json').write_text(serialized, encoding='utf-8')
    empty_headers = {
        'data_quality_summary': ('severity', 'rule', 'n'),
        'data_quality_issues': ('source_row', 'resident_id', 'rule', 'severity', 'explanation'),
        'resident_metrics': ('resident_id', 'source_row', 'los_category', 'los_days'),
        'followup_detail': ('resident_id', 'horizon_months', 'anchor_date', 'due_date',
                            'recorded_value', 'analysis_bucket'),
    }
    for key in ('funnel', 'stage_durations', 'stage_unresolved', 'monthly_occupancy', 'outcomes',
                'data_quality_summary', 'data_quality_issues', 'resident_metrics', 'followup_detail'):
        write_csv(output_path / f'{key}.csv', result[key], empty_headers.get(key, ()))
    write_csv(output_path / 'los.csv', [{'cohort': k, **result['los'][k]} for k in
              ('ended_stays', 'ongoing_elapsed_stays', 'program_completed_subset')])
    (output_path / 'REPORT.md').write_text(report(result), encoding='utf-8')
    (output_path / 'dashboard.html').write_text(dashboard(result), encoding='utf-8')


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path)
    p.add_argument('--as-of', required=True, type=date.fromisoformat, help='Confirmed data snapshot cutoff, YYYY-MM-DD')
    p.add_argument('--out', type=Path, default=Path('outputs'))
    p.add_argument('--fiscal-year', type=int, help='Jan-Dec year; default all history through --as-of')
    p.add_argument('--capacity', type=int, help='Explicit constant capacity override')
    p.add_argument('--followup-anchor', choices=('discharge', 'admission'), default='discharge')
    p.add_argument('--occupancy-start', type=date.fromisoformat, help='Default: first usable admission, inclusive')
    args = p.parse_args()
    try:
        result = calculate_file(args.input, args.as_of, capacity=args.capacity,
                                anchor=args.followup_anchor, start=args.occupancy_start,
                                fiscal_year=args.fiscal_year)
        export_result(result, args.out)
    except (ValueError, OSError) as exc:
        p.error(str(exc))
    print(report(result))
    print(f'Outputs saved to {args.out.resolve()}')


if __name__ == '__main__':
    main()

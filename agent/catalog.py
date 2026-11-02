"""Reviewed semantic catalog; identifiers here are code constants, never model SQL."""
VERSION = '2.2.0'
METRICS = {
    'monthly_activity': dict(table='derived_monthly_activity', page='pages/funnel.py', label='Monthly referral, intake and admission activity',
                            views=['event_counts'], filters=['month', 'event'], dimensions=['month', 'event'],
                            charts=['line', 'bar', 'grouped_bar', 'table']),
    'funnel': dict(table='funnel', page='pages/funnel.py', label='Referral funnel',
                   views=['stages', 'stage_count', 'conversion'], filters=['stage'],
                   dimensions=['stage'], charts=['funnel', 'bar', 'table']),
    'occupancy': dict(table='monthly_occupancy', page='pages/occupancy.py', label='Occupancy',
                     views=['bounds', 'weighted_lower'], filters=['month'],
                     dimensions=['month'], charts=['line', 'bar', 'table']),
    'outcomes': dict(table='outcomes', page='pages/outcomes.py', label='Follow-up outcomes',
                    views=['breakdown', 'coverage', 'reported_relapse_share'], filters=['horizon_months'],
                    dimensions=['horizon_months', 'outcome'], charts=['bar', 'grouped_bar', 'table']),
    'los': dict(table='los', page='pages/los.py', label='Length of stay',
               views=['cohort_statistics'], filters=['cohort'], dimensions=['cohort'],
               charts=['bar', 'grouped_bar', 'table']),
    'quality': dict(table='data_quality_summary', page='pages/quality.py', label='Data quality',
                   views=['flag_count'], filters=['severity', 'rule'],
                   dimensions=['rule', 'severity'], charts=['bar', 'table']),
}
STAGES = ['referral', 'intake', 'admission', 'discharge']
COHORTS = ['ended_stays', 'ongoing_elapsed_stays', 'program_completed_subset']
DEFAULT_VIEWS = dict(monthly_activity='event_counts', funnel='stages', occupancy='bounds', outcomes='breakdown',
                     los='cohort_statistics', quality='flag_count')
NOTES = {
    'monthly_activity': 'Recorded event counts by each event date, within the selected report and cutoff. '
                        'Referrals, intakes and admissions are independent series, not a strict referral-cohort '
                        'conversion funnel; an intake/admission can follow a referral in a prior year. Missing '
                        'or invalid dates are excluded. Zero means no recorded events, not verified complete activity.',
    'funnel': 'Strict milestone order. Stage display selection does not redefine conversion denominators.',
    'occupancy': 'Known lower / possible upper bounds, not confidence intervals or exact occupancy. Period rates use bed-day weighting; values above 100% are retained.',
    'outcomes': 'All due residents remain in the denominator. Engagement is not verified sobriety. Follow-up observation dates are unavailable; horizons are separate cohorts, not additive residents.',
    'los': 'Ended, ongoing elapsed and program-completed cohorts are separate. Ongoing elapsed stays are right-censored; medians/P90 cannot be pooled.',
    'quality': 'Counts are rule flags, not distinct residents. One resident can trigger multiple flags.',
}


def make_spec(metric, intent='chart', view=None, filters=None, chart=None, force=False):
    result = dict(schema_version='2.0', intent=intent, metric=metric,
                  view=view or DEFAULT_VIEWS[metric], filters=filters or [],
                  time_window={'mode': 'report'})
    if intent == 'chart':
        result['output'] = dict(type='chart', chart_type=chart or METRICS[metric]['charts'][0],
                                title=METRICS[metric]['label'], sort='source', force_new=force)
    else:
        result['output'] = {'type': 'scalar' if result['view'] in
                            ('weighted_lower', 'coverage', 'reported_relapse_share', 'stage_count', 'conversion') else 'table'}
    return result

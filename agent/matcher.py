"""Only route to an existing chart when its actual controls cover the intent."""
from .catalog import METRICS


def match(spec):
    metric = spec['metric']
    if metric == 'monthly_activity':
        # The strict funnel page is related, but cannot display the event-date series.
        return None
    result = dict(page=METRICS[metric]['page'], label=METRICS[metric]['label'])
    if spec['intent'] == 'navigate':
        return dict(**result, message='Open the corresponding page to view its charts and metric definitions.')
    if spec['intent'] != 'chart' or spec['output'].get('force_new'):
        return None
    chart, view = spec['output']['chart_type'], spec['view']
    filters = {item['field']: item['value'] for item in spec['filters']}
    message = None
    if metric == 'occupancy' and view == 'bounds' and chart == 'line':
        months = filters.get('month')
        message = 'Use the Displayed month window slider ' + (f'to select {months[0]} through {months[1]}.' if months else 'to select a month range.')
    elif metric == 'outcomes' and view == 'breakdown' and chart == 'bar':
        horizon = filters.get('horizon_months')
        if isinstance(horizon, list) and len(horizon) == 1:
            horizon = horizon[0]
        if horizon in (6, 12):
            result = dict(page='pages/overview.py', label='Overview follow-up composition')
            message = f'Select {horizon} Months under Follow-up period on Overview to see all seven categories. On the detail page, select {horizon} Months to see the three main bars and notes on the remaining categories.'
    elif metric == 'funnel' and view == 'stages' and chart == 'funnel':
        message = 'View the complete strict funnel. Stage filters affect the display only and preserve the original conversion denominators.'
    elif metric == 'los' and chart == 'grouped_bar':
        message = 'Use LOS cohorts to select cohorts and compare their median/P90 values separately. Do not pool the cohorts.'
    elif metric == 'quality' and chart == 'bar' and not any(f['field'] == 'rule' for f in spec['filters']):
        message = 'Use the Severity filter' + (f' to select {filters["severity"]}. ' if 'severity' in filters else '. ') + 'Counts represent rule flags, not distinct residents.'
    if message:
        return dict(**result, message=message)
    return None

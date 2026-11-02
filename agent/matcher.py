"""Only route to an existing chart when its actual controls cover the intent."""
from .catalog import METRICS


def match(spec):
    metric = spec['metric']
    if metric == 'monthly_activity':
        # The strict funnel page is related, but cannot display the event-date series.
        return None
    result = dict(page=METRICS[metric]['page'], label=METRICS[metric]['label'])
    if spec['intent'] == 'navigate':
        return dict(**result, message='打开对应页面查看现有图表与指标说明。')
    if spec['intent'] != 'chart' or spec['output'].get('force_new'):
        return None
    chart, view = spec['output']['chart_type'], spec['view']
    filters = {item['field']: item['value'] for item in spec['filters']}
    message = None
    if metric == 'occupancy' and view == 'bounds' and chart == 'line':
        months = filters.get('month')
        message = '使用 Displayed month window 滑块' + (f'选择 {months[0]} 至 {months[1]}。' if months else '选择月份范围。')
    elif metric == 'outcomes' and view == 'breakdown' and chart == 'bar':
        horizon = filters.get('horizon_months')
        if isinstance(horizon, list) and len(horizon) == 1:
            horizon = horizon[0]
        if horizon in (6, 12):
            result = dict(page='pages/overview.py', label='Overview follow-up composition')
            message = f'在 Overview 找到 {horizon}-month follow-up 图，查看完整七类构成。详情页可选择 {horizon} Months 查看三类柱及其他类别说明。'
    elif metric == 'funnel' and view == 'stages' and chart == 'funnel':
        message = '查看完整严格漏斗；阶段筛选仅影响展示，不改变既有转化分母。'
    elif metric == 'los' and chart == 'grouped_bar':
        message = '通过 LOS cohorts 选择 cohort，比较各自 median/P90；不要合并 cohort。'
    elif metric == 'quality' and chart == 'bar' and not any(f['field'] == 'rule' for f in spec['filters']):
        message = '使用 Severity 筛选' + (f'选择 {filters["severity"]}；' if 'severity' in filters else '；') + '图中计数是规则标记数，并非独立居民数。'
    if message:
        return dict(**result, message=message)
    return None

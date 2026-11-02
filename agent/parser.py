"""Gemini-first intent parsing; legacy rules require explicit administrator selection."""
import copy
import os
import re
from .catalog import METRICS, make_spec
from .spec import validate

TOPICS = dict(funnel=r'funnel|漏斗|referral|转介|intake|admission|入院|discharge|出院人数',
              occupancy=r'occupancy|入住率|床日', outcomes=r'follow.?up|outcome|coverage|relapse|随访|覆盖率|复发',
              los=r'(?<![a-z])los(?![a-z])|length of stay|住院时长|居住时长|中位.*天|median',
              quality=r'quality|质量|flag|标记')


def rejected(message):
    return dict(action='rejected', message=message)


def gate(question):
    if not isinstance(question, str) or not question.strip() or len(question) > 1200:
        raise ValueError('Enter an operational analytics question of up to 1,200 characters.')
    if re.search(r'(?i)\b(select|attach|copy|insert|delete|drop|pragma|install|execute|read_csv|read_text|tenant_id|api.key|staff_note|resident_id)\b|忽略.*指令|ignore.*instructions|[A-Za-z]:[\\/]|https?://|[\w.+-]+@[\w.-]+|\b\d{3}[- .]\d{3}[- .]\d{4}\b|居民姓名|手机号|身份证|出生日期|某位居民|individual resident|patient name', question):
        raise ValueError('Only aggregate operational questions are supported. Remove personal information, paths, SQL or execution instructions.')
    if re.search(r'(?i)age group|年龄|gender|性别|survival|生存曲线|histogram|直方图|causal|因果|预测', question):
        raise ValueError('The current aggregates do not support that dimension or analysis. Resident-level records cannot be reconstructed from summary tables.')


def horizons(text):
    result = []
    for horizon in (6, 12):
        if re.search(rf'(?<!\d){horizon}(?:\s*[- ]?\s*(?:month|个月|月))', text, re.I):
            result.append(horizon)
    if re.search(r'6\s*(?:/|和|与|及|and|vs|versus)\s*12', text, re.I):
        result = [6, 12]
    return result


def clarification(metric, view, message, base=None):
    return dict(action='clarify', message=message,
                pending=dict(metric=metric, view=view, base=base))


def rule_parse(question, pending=None, previous=None):
    text = question.strip().lower()
    if re.search(r'\bsober\b|清醒|戒酒|successful|成功率|\bactive\b|活跃', text):
        return clarification('undefined', 'definition', 'Specify the recorded category, follow-up period and denominator. engaged_in_recovery does not prove verified sobriety; restate the request using a defined metric.')
    if pending:
        hs = horizons(text)
        if pending['metric'] == 'outcomes':
            if not hs:
                return clarification('outcomes', pending['view'], 'Choose 6-month or 12-month follow-up and confirm that all residents due are the denominator.', pending.get('base'))
            if pending['view'] == 'reported_relapse_share' and not re.search(r'全部|所有|到期|all|due', text):
                return clarification('outcomes', pending['view'], 'Should all residents due be the denominator? Please explicitly confirm "all residents due".', pending.get('base'))
            spec = copy.deepcopy(pending.get('base')) or make_spec('outcomes', 'value', pending['view'])
            spec['filters'] = [dict(field='horizon_months', op='eq' if len(hs) == 1 else 'in', value=hs[0] if len(hs) == 1 else hs)]
            if len(hs) > 1 and spec['output']['type'] == 'scalar':
                spec['output']['type'] = 'table'
            return dict(action='spec', spec=validate(spec))
        if pending['metric'] == 'los':
            cohort = next((c for c in ('ended_stays', 'ongoing_elapsed_stays', 'program_completed_subset') if c in text), None)
            if not cohort:
                return clarification('los', 'cohort_statistics', 'Choose ended_stays, ongoing_elapsed_stays or program_completed_subset.')
            return dict(action='spec', spec=make_spec('los', 'value', filters=[dict(field='cohort', op='eq', value=cohort)]))
    topics = [m for m, pattern in TOPICS.items() if re.search(pattern, text)]
    if previous and previous.get('intent') == 'chart' and re.search(r'改|换|只保留|加入|change|switch|only|add', text):
        spec = copy.deepcopy(previous)
        if re.search(r'柱|bar', text):
            spec['output']['chart_type'] = 'bar'
        if re.search(r'折线|line', text):
            spec['output']['chart_type'] = 'line'
        if re.search(r'降序|descending', text):
            spec['output']['sort'] = 'descending'
        hs = horizons(text)
        if spec['metric'] == 'outcomes' and hs:
            spec['filters'] = [dict(field='horizon_months', op='eq' if len(hs) == 1 else 'in', value=hs[0] if len(hs) == 1 else hs)]
        spec['output']['force_new'] = True
        return dict(action='spec', spec=validate(spec))
    if re.search(r'报告|report', text) and re.search(r'生成|整理|专题|摘要|create|generate|summary', text):
        if re.search(r'\d{4}[-年]\d{1,2}|季度|quarter|今年|去年|本月|上月|this year|last year', text):
            return rejected('The report generator uses the entire selected report. For a month range, generate a standalone chart; month-specific reports are not yet available.')
        return dict(action='spec', spec=validate(dict(schema_version='2.0', intent='report',
                     title='Operational analysis report', sections=topics or ['occupancy', 'outcomes'])))
    if len(topics) != 1:
        return rejected('Specify funnel, occupancy, follow-up, LOS or data quality. Use "Generate an occupancy and follow-up report" to combine topics.')
    metric = topics[0]
    if re.search(r'今年|去年|本月|上月|今天|this year|last year|last month|today', text):
        return rejected('Specify a report year or YYYY-MM range. The report cutoff does not automatically change with today\'s date.')
    if re.search(r'哪里|在哪|打开|where|open|navigate', text):
        return dict(action='spec', spec=dict(schema_version='2.0', intent='navigate', metric=metric))
    is_chart = bool(re.search(r'画|图|plot|chart|graph|趋势|trend|比较|compare', text))
    intent = 'chart' if is_chart else 'value'
    spec = make_spec(metric, intent)
    if metric == 'outcomes':
        view = ('reported_relapse_share' if re.search(r'复发率|relapse rate|relapse share', text) else
                'coverage' if re.search(r'覆盖|coverage', text) else 'breakdown')
        hs = horizons(text)
        spec = make_spec(metric, intent, view)
        if not hs or (view == 'reported_relapse_share' and not re.search(r'全部|所有|到期|all|due', text)):
            return clarification(metric, view, 'Choose 6-month or 12-month follow-up. Should the reported relapse proportion use all residents due as its denominator?', spec)
        spec['filters'] = [dict(field='horizon_months', op='eq' if len(hs) == 1 else 'in', value=hs[0] if len(hs) == 1 else hs)]
        if len(hs) > 1 and intent == 'value':
            spec['output']['type'] = 'table'
    elif metric == 'occupancy':
        if not is_chart or re.search(r'加权|整体|weighted|overall', text):
            spec = make_spec(metric, intent, 'weighted_lower', chart='bar')
        months = re.findall(r'(?<!\d)(\d{4}-\d{2})(?![-\d])', text)
        chinese_months = re.findall(r'(\d{4})年\s*(\d{1,2})月', text)
        months += [f'{int(year):04d}-{int(month):02d}' for year, month in chinese_months]
        if re.search(r'\d{4}-\d{2}-\d{2}|季度|quarter|每天|daily', text):
            return rejected('This prototype supports complete-month ranges, not day-level slices or quarterly regrouping. Use YYYY-MM through YYYY-MM.')
        if months:
            spec['filters'] = [dict(field='month', op='between', value=[min(months), max(months)])]
        elif re.search(r'(?<!\d)\d{1,2}\s*(?:至|到|–|-)\s*\d{1,2}\s*月', text):
            return rejected('Specify the year using YYYY-MM through YYYY-MM so the current year is not mistaken for the report year.')
        elif re.search(r'(?<!\d)\d{1,2}月|january|february|march|april|may|june|july|august|september|october|november|december', text):
            return rejected('Use an explicit YYYY-MM or YYYY-MM through YYYY-MM range.')
    elif metric == 'funnel':
        stage = next((stage for stage, pattern in [('admission', r'admission|入院'), ('referral', r'referral|转介'),
                      ('intake', r'intake'), ('discharge', r'discharge|出院人数')] if re.search(pattern, text)), None)
        if stage and not is_chart:
            view = 'conversion' if re.search(r'转化|conversion', text) else 'stage_count'
            spec = make_spec(metric, intent, view, filters=[dict(field='stage', op='eq', value=stage)])
    elif metric == 'los' and not is_chart:
        cohort = next((c for c in ('ended_stays', 'ongoing_elapsed_stays', 'program_completed_subset') if c in text), None)
        if not cohort:
            return clarification('los', 'cohort_statistics', 'Choose ended_stays, ongoing_elapsed_stays or program_completed_subset. Cohort medians cannot be pooled.')
        spec['filters'] = [dict(field='cohort', op='eq', value=cohort)]
    elif metric == 'quality' and not is_chart:
        spec['output'] = {'type': 'scalar'}
    if intent == 'chart':
        if re.search(r'柱|bar', text):
            spec['output']['chart_type'] = 'bar'
        if re.search(r'折线|line', text):
            spec['output']['chart_type'] = 'line'
        spec['output']['force_new'] = bool(re.search(r'另画|重新画|新图|new chart|new plot|同一张|一张.*比较', text))
    return dict(action='spec', spec=validate(spec))


def api_parse(question, previous=None):
    """Compatibility entry point; API mode now means native Gemini."""
    from .gemini import parse_with_gemini
    return parse_with_gemini(question, previous=previous)


def parse(question, pending=None, previous=None):
    gate(question)
    mode = os.environ.get('HARBOURVIEW_AGENT_MODE', 'gemini').strip().lower()
    if mode == 'rules':
        return rule_parse(question, pending, previous)
    if mode not in ('gemini', 'api'):
        raise ValueError('Unsupported HARBOURVIEW_AGENT_MODE. Use gemini (default) or explicit rules.')
    from .gemini import parse_with_gemini
    return parse_with_gemini(question, pending=pending, previous=previous)

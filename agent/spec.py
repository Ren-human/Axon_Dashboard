"""Structural and semantic validation; all entry points use the same contract."""
import copy
import json
import re
from datetime import datetime
from pathlib import Path
from jsonschema import Draft202012Validator
from .catalog import METRICS, STAGES, COHORTS

SCHEMA = json.loads(Path(__file__).with_name('spec.schema.json').read_text(encoding='utf-8'))
VALIDATOR = Draft202012Validator(SCHEMA)


def validate(spec):
    if not isinstance(spec, dict) or len(json.dumps(spec, ensure_ascii=False)) > 12000:
        raise ValueError('Invalid or oversized specification.')
    if next(VALIDATOR.iter_errors(spec), None) is not None:
        raise ValueError('Specification does not match the approved JSON schema.')
    if spec['intent'] in ('navigate', 'report'):
        return copy.deepcopy(spec)
    metric, view, output = spec['metric'], spec['view'], spec['output']
    info = METRICS[metric]
    if view not in info['views']:
        raise ValueError('Unsupported metric/view combination.')
    if spec['intent'] == 'chart':
        if output['type'] != 'chart' or output.get('chart_type') not in info['charts']:
            raise ValueError('Unsupported chart for this metric.')
        if output.get('chart_type') == 'funnel' and (view != 'stages' or output.get('sort', 'source') != 'source'):
            raise ValueError('A strict funnel requires its original stages and order.')
    elif output['type'] == 'chart' or set(output) != {'type'}:
        raise ValueError('A value request must use scalar/table output only.')
    if output['type'] == 'scalar' and view not in ('stage_count', 'conversion', 'weighted_lower', 'coverage', 'reported_relapse_share', 'flag_count'):
        raise ValueError('This view is not a scalar.')
    seen = set()
    for item in spec['filters']:
        field, op, value = item['field'], item['op'], item['value']
        if field not in info['filters'] or field in seen:
            raise ValueError('Unsupported or duplicate filter.')
        seen.add(field)
        values = value if isinstance(value, list) else [value]
        if op == 'in' and len(set(values)) != len(values):
            raise ValueError('Duplicate category values are not allowed.')
        if (op == 'eq' and isinstance(value, list)) or (op != 'eq' and not isinstance(value, list)):
            raise ValueError('Filter operator/value shape mismatch.')
        if field == 'month':
            if op != 'between' or len(values) != 2:
                raise ValueError('Month selection requires a complete-month range.')
            for val in values:
                if not isinstance(val, str) or not re.fullmatch(r'\d{4}-\d{2}', val):
                    raise ValueError('Expected YYYY-MM.')
                datetime.strptime(val, '%Y-%m')
            if values[0] > values[1]:
                raise ValueError('Reversed month range.')
        else:
            if op not in ('eq', 'in'):
                raise ValueError('Unsupported filter operator.')
            allowed = {'stage': STAGES, 'event': ['referral', 'intake', 'admission'],
                       'cohort': COHORTS, 'horizon_months': [6, 12]}.get(field)
            if allowed and any(type(v) is bool or v not in allowed for v in values):
                raise ValueError('Unsupported filter value.')
            if field in ('severity', 'rule') and any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError('Expected a nonempty category.')
    if metric == 'outcomes' and 'horizon_months' not in seen:
        raise ValueError('Specify 6 or 12 months, or explicitly compare both.')
    if view in ('stage_count', 'conversion') and 'stage' not in seen:
        raise ValueError('Specify the funnel stage.')
    if output['type'] == 'scalar':
        for item in spec['filters']:
            if item['field'] in ('stage', 'horizon_months') and isinstance(item['value'], list) and len(item['value']) != 1:
                raise ValueError('Multiple groups require table or chart output.')
    return copy.deepcopy(spec)

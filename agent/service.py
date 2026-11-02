"""Bounded orchestration shared by chat, JSON editor, and regression tests."""
import hashlib
import json
import re
import uuid
from . import VERSION
from .catalog import METRICS, make_spec
from .parser import parse
from .spec import validate
from .query import execute, QUERY_VERSION
from .results import analyze
from .matcher import match
from .report_builder import render_report


def source_info(context, metadata):
    info = json.loads(metadata.to_json(orient='records'))[0]
    # Metadata allow-list already selected by the worker; exclude any internal paths.
    return dict(report=context.report, fingerprint=context.fingerprint, agent_version=VERSION,
                query_version=QUERY_VERSION, **info)


def stamp(result, context):
    payload = json.dumps(result['spec'], sort_keys=True, ensure_ascii=True) + context.fingerprint
    result['evidence_id'] = hashlib.sha256(payload.encode()).hexdigest()[:20]
    return result


def execute_spec(spec, context):
    spec = validate(spec)
    intent = spec['intent']
    if intent == 'navigate':
        if spec['metric'] == 'monthly_activity':
            return execute_spec(make_spec('monthly_activity',force=True),context)
        return dict(action='guided', guide=match(spec), spec=spec, identity=context.identity)
    metrics = spec['sections'] if intent == 'report' else [spec['metric']]
    tables = execute(context, metrics)
    source = source_info(context, tables['metadata'])
    if intent == 'report':
        sections = []
        for index, metric in enumerate(metrics):
            chart = dict(monthly_activity='line',funnel='funnel', occupancy='line', outcomes='bar', los='grouped_bar', quality='bar')[metric]
            item = make_spec(metric, chart=chart, force=True)
            if index >= 4:
                item['output']['chart_type'] = 'table'
            if metric == 'outcomes':
                item = make_spec(metric, view='coverage', chart='bar', force=True,
                                 filters=[dict(field='horizon_months', op='in', value=[6, 12])])
            try:
                section = stamp(analyze(validate(item), tables), context)
                if metric == 'occupancy':
                    extra = make_spec(metric, 'value', 'weighted_lower')
                    section['summary'] = stamp(analyze(validate(extra), tables), context)
                elif metric == 'outcomes':
                    extra = make_spec(metric, 'value', 'breakdown',
                                      filters=[dict(field='horizon_months', op='in', value=[6, 12])])
                    section['detail'] = stamp(analyze(validate(extra), tables), context)
                sections.append(section)
            except ValueError:
                sections.append(dict(metric=metric, error=True))
        report = render_report(spec['title'], sections, source)
        return dict(action='report', report=report, spec=spec, identity=context.identity)
    result = stamp(analyze(spec, tables), context)
    guide = match(spec) if intent == 'chart' else None
    return dict(action='guided' if guide else 'result', guide=guide, result=result,
                source=source, spec=spec, identity=context.identity)


def handle(question, context, pending=None, previous=None):
    # Explicit years must match the selected report, checked after the query too.
    parsed = parse(question, pending=pending, previous=previous)
    if parsed['action'] != 'spec':
        return dict(**parsed, identity=context.identity)
    result = execute_spec(parsed['spec'], context)
    source = result.get('source') or result.get('report', {}).get('source')
    # Carry the original request's year through LLM clarification turns as well.
    year_text = parsed.get('request_text', question)
    years = set(re.findall(r'(?<!\d)(?:FY\s*)?(20\d{2})(?!\d|[-/]\d{2})', year_text, re.I))
    if source and years:
        fiscal = str(source.get('fiscal_year'))
        if fiscal.endswith('.0'):
            fiscal = fiscal[:-2]
        if any(year != fiscal for year in years):
            raise ValueError('Requested year differs from the selected report. Select its authorized report first.')
    return result

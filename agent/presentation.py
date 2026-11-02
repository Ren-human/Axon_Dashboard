"""Streamlit presentation; session records retain their original report identity."""
from pathlib import Path
import json
import os
import uuid
import pandas as pd
import streamlit as st
from .context import local_context
from .service import handle, execute_spec
from .chart_builder import build
from .audit import record


def show(reply, key):
    action = reply['action']
    if action in ('clarify', 'rejected', 'error'):
        st.write(reply['message'])
        return
    identity = reply.get('identity')
    if identity:
        st.caption(f'Report: {identity[1]} · fingerprint {identity[2][:12]}')
    guide = reply.get('guide')
    if guide:
        st.write('已有页面可以满足这项需求。' + guide['message'])
        st.page_link(guide['page'], label='Open ' + guide['label'])
    if action == 'result':
        result = reply['result']
        st.write(result['spec']['output'].get('title') or result['view'])
        if result['spec']['output']['type'] == 'scalar' and result['rows']:
            row = result['rows'][0]
            value = row.get('value', row.get('n'))
            display = 'N/A' if value is None else f'{value:.1%}' if result['unit'].startswith('fraction') else f'{value:,.0f}'
            st.metric(result['view'], display)
        elif result['spec']['output']['type'] == 'chart':
            fig = build(result)
            if fig is not None:
                st.plotly_chart(fig, width='stretch', key=key + '_chart')
        st.dataframe(pd.DataFrame(result['rows'], columns=result['columns']), hide_index=True)
        st.caption('Unit: ' + result['unit'] + ' · ' + result['note'])
        from .catalog import METRICS
        label = 'Open related strict-funnel page' if result['metric']=='monthly_activity' else 'Open source page'
        st.page_link(METRICS[result['metric']]['page'], label=label)
    if action == 'report':
        report = reply['report']
        st.write(report['title'])
        st.caption('Status: ' + report['status'])
        if report['status'] != 'complete':
            st.warning('Partial report: unavailable sections are marked; no complete conclusion is asserted.')
        for i, section in enumerate(report['sections']):
            with st.expander(section['metric'], expanded=True):
                if section.get('error'):
                    st.warning('Unavailable: validation failed.')
                    continue
                fig = build(section)
                if fig is not None:
                    st.plotly_chart(fig, width='stretch', key=f'{key}_section_{i}')
                st.dataframe(pd.DataFrame(section['rows'], columns=section['columns']), hide_index=True)
                for name in ('summary', 'detail'):
                    if name in section:
                        extra = section[name]
                        st.caption(name.title() + ' · ' + extra['unit'])
                        st.dataframe(pd.DataFrame(extra['rows'], columns=extra['columns']), hide_index=True)
                st.caption(section['note'])
        st.download_button('Download report · HTML (offline)', report['html'].encode('utf-8'),
                           'operational-report.html', 'text/html', key=key + '_html')
        st.download_button('Download report · Markdown', report['markdown'].encode('utf-8'),
                           'operational-report.md', 'text/markdown', key=key + '_md')
    with st.expander('Specification & provenance'):
        st.json(reply.get('spec', {}))
        st.json(reply.get('source') or reply.get('report', {}).get('source', {}))


def render():
    root = Path(__file__).resolve().parents[1]
    st.subheader('AI Analyst')
    mode = os.environ.get('HARBOURVIEW_AGENT_MODE', 'gemini').strip().lower()
    if mode == 'rules':
        st.caption('Explicit rule demo mode · no LLM calls')
    elif mode in ('gemini', 'api'):
        from .gemini import settings
        try:
            key, model = settings()
            st.caption(f'Gemini LLM planner · {model} · query results stay local')
            if not key:
                st.info('Gemini is the default. Add GEMINI_API_KEY to the environment or '
                        '.streamlit/secrets.toml to enable chat. No automatic rule fallback is used.')
        except ValueError as exc:
            st.info(str(exc))
    else:
        st.info('Unsupported model mode. Set HARBOURVIEW_AGENT_MODE to gemini or rules.')
    st.caption('Local single-user demo identity. Only registered aggregate reports are queryable.')
    try:
        context = local_context(root, st.session_state['db_path'])
    except (OSError, ValueError, KeyError):
        st.info('当前报告未获准供 agent 查询。请选择已登记报告；现有分析页面仍可使用。')
        return
    if st.session_state.get('agent_identity') != context.identity:
        st.session_state['agent_pending'] = None
        st.session_state['agent_previous'] = None
        st.session_state['agent_identity'] = context.identity
    history = st.session_state.setdefault('agent_history', [])
    with st.expander('Example questions'):
        st.write('哪里可以看入住率？\n\n当前报告6月随访覆盖率是多少？\n\n把6月和12月随访覆盖率画在同一张图。\n\n生成入住率与随访专题报告。')
    # Bound memory: reports embed a local JS bundle, so retain only 8 exchanges.
    # Keep long answers, charts and reports inside the chat's own scroll surface.
    # The stable key preserves the container; the input stays immediately below it.
    with st.container(height=480, border=True, key='agent_messages'):
        if not history:
            st.caption('Ask a question below. Conversation history appears here.')
        for i, entry in enumerate(history):
            with st.chat_message('user'):
                st.text(entry['question'])
            with st.chat_message('assistant'):
                show(entry['reply'], f'agent_{entry["id"]}_{i}')
    prompt = st.chat_input('Ask about operational metrics...', key='overview_agent')
    manual = None
    with st.expander('Advanced · validated JSON specification'):
        text = st.text_area('JSON specification', value='{}', key='agent_spec_editor', height=130)
        if st.button('Run specification', key='agent_run_spec'):
            manual = text
        if st.session_state.get('agent_previous'):
            st.caption('Last validated specification:')
            st.json(st.session_state['agent_previous'])
    if st.button('Clear analyst conversation', key='agent_clear'):
        for name in ('agent_history', 'agent_pending', 'agent_previous'):
            st.session_state.pop(name, None)
        st.rerun()
    if prompt or manual is not None:
        request_id = uuid.uuid4().hex
        try:
            with st.spinner('Validating and querying aggregates...'):
                reply = execute_spec(json.loads(manual), context) if manual is not None else handle(
                    prompt, context, st.session_state.get('agent_pending'), st.session_state.get('agent_previous'))
            st.session_state['agent_pending'] = reply.get('pending')
            if reply.get('spec'):
                st.session_state['agent_previous'] = reply['spec']
        except (ValueError, OSError) as exc:
            # Boundary errors contain safe messages; OS exception details are withheld.
            message = str(exc) if isinstance(exc, ValueError) else 'Local operation failed; no result published.'
            reply = dict(action='error', message=message, identity=context.identity)
        try:
            record(root, context, request_id, reply['action'], reply.get('spec'))
        except OSError:
            reply = dict(action='error', message='Audit write failed; result withheld.', identity=context.identity)
        history.append(dict(id=request_id, question=prompt or '[Validated JSON request]', reply=reply))
        del history[:-8]
        st.rerun()

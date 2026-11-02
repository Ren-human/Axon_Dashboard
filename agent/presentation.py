"""Compact and full-page views over one report-bound analyst conversation."""
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


def full_report(report,key):
    for i,section in enumerate(report['sections']):
        with st.expander(section['metric'],expanded=True):
            if section.get('error'):
                st.warning('Unavailable: validation failed.')
                continue
            fig = build(section)
            if fig is not None:
                st.plotly_chart(fig,width='stretch',key=f'{key}_section_{i}')
            st.dataframe(pd.DataFrame(section['rows'],columns=section['columns']),hide_index=True)
            for name in ('summary','detail'):
                if name in section:
                    extra = section[name]
                    st.caption(name.title()+' · '+extra['unit'])
                    st.dataframe(pd.DataFrame(extra['rows'],columns=extra['columns']),hide_index=True)
            st.caption(section['note'])
    st.download_button('Download report · HTML (offline)',report['html'].encode('utf-8'),
                       'operational-report.html','text/html',key=key+'_html')
    st.download_button('Download report · Markdown',report['markdown'].encode('utf-8'),
                       'operational-report.md','text/markdown',key=key+'_md')


def show(reply,key,compact=False):
    action = reply['action']
    if action in ('clarify','rejected','error'):
        st.write(reply['message'])
        return
    identity = reply.get('identity')
    if identity:
        st.caption(f'Report: {identity[1][:8]} · {identity[2][:8]}' if compact else
                   f'Report: {identity[1]} · fingerprint {identity[2][:12]}')
    guide = reply.get('guide')
    if guide:
        st.write('An existing page can answer this request. '+guide['message'])
        st.page_link(guide['page'],label='Open '+guide['label'])
    if action=='result':
        result = reply['result']
        output = result['spec']['output']
        if output['type']!='scalar':
            st.write(output.get('title') or result['view'])
        if output['type']=='scalar' and result['rows']:
            row = result['rows'][0]
            number = row.get('value',row.get('n'))
            display = 'N/A' if number is None else f'{number:.1%}' if result['unit'].startswith('fraction') else f'{number:,.0f}'
            label = {'coverage':'Follow-up coverage','reported_relapse_share':'Recorded relapse share',
                     'weighted_lower':'Known occupancy lower bound','conversion':'Stage conversion',
                     'stage_count':'Stage count','flag_count':'Quality flags'}.get(result['view'],result['view'])
            st.metric(label,display)
            if compact and 'numerator' in row and 'denominator' in row:
                st.caption(f"Numerator / denominator: {row['numerator']:g} / {row['denominator']:g}")
        elif output['type']=='chart':
            fig = build(result)
            if fig is not None:
                if compact:
                    fig.update_layout(height=220,font=dict(size=11),margin=dict(l=8,r=8,t=12,b=30))
                st.plotly_chart(fig,width='stretch',key=key+'_chart')
            if compact:
                st.page_link('pages/analyst.py',label='Expand chart ↗')
        frame = pd.DataFrame(result['rows'],columns=result['columns'])
        if not compact:
            st.dataframe(frame,hide_index=True)
        elif output['type']=='table':
            st.dataframe(frame.head(5),hide_index=True,height=180)
            st.caption(f'Preview: {min(5,len(frame))} of {len(frame)} rows')
            st.page_link('pages/analyst.py',label='View full results ↗')
        if compact:
            notes = {'outcomes':'All due residents remain in the denominator. Engagement is not verified sobriety.',
                     'occupancy':'Known lower / possible upper bounds. Period rates use bed-day weighting.',
                     'monthly_activity':'Event-date counts, not a strict referral-cohort funnel. Missing dates are excluded.',
                     'funnel':'Strict milestone order; original conversion denominators are preserved.',
                     'los':'Cohorts stay separate. Ongoing stays show censored elapsed time.',
                     'quality':'Rule flags, not unique residents.'}
            st.caption(notes[result['metric']])
        else:
            st.caption('Unit: '+result['unit']+' · '+result['note'])
        from .catalog import METRICS
        label = 'Open related strict-funnel page' if result['metric']=='monthly_activity' else 'Open source page'
        st.page_link(METRICS[result['metric']]['page'],label=label)
    if action=='report':
        report = reply['report']
        st.write(report['title'])
        st.caption('Status: '+report['status'])
        if report['status']!='complete':
            st.warning('Partial report: unavailable sections are marked; no complete conclusion is asserted.')
        if compact:
            st.write('Sections: '+', '.join(section['metric'] for section in report['sections']))
            st.page_link('pages/analyst.py',label='View full report & downloads ↗')
        else:
            full_report(report,key)
    if not compact:
        with st.expander('Specification & provenance'):
            st.json(reply.get('spec',{}))
            st.json(reply.get('source') or reply.get('report',{}).get('source',{}))


def render(*,compact=False):
    root = Path(__file__).resolve().parents[1]
    title,link = st.columns([1,1] if compact else [4,1],vertical_alignment='center')
    with title:
        st.markdown('#### AI Analyst' if compact else '### AI Analyst')
    with link:
        st.page_link('pages/analyst.py' if compact else 'pages/overview.py',
                     label='Open full chat ↗' if compact else '← Overview')
    mode = os.environ.get('HARBOURVIEW_AGENT_MODE','gemini').strip().lower()
    if mode=='rules':
        st.caption('Explicit rule demo mode · no LLM calls')
    elif mode in ('gemini','api'):
        from .gemini import settings
        try:
            key,model = settings()
            st.caption('Ask about this report' if compact else f'Gemini · {model} · query results stay local')
            if not key:
                st.info('Add GEMINI_API_KEY to the environment or .streamlit/secrets.toml to enable chat. No automatic rule fallback is used.')
        except ValueError as exc:
            st.info(str(exc))
    else:
        st.info('Unsupported model mode. Set HARBOURVIEW_AGENT_MODE to gemini or rules.')
    try:
        context = local_context(root,st.session_state['db_path'])
    except (OSError,ValueError,KeyError):
        st.info('This report is not authorized for analyst queries. Select a registered report; the analysis pages remain available.')
        return
    if st.session_state.get('agent_identity')!=context.identity:
        st.session_state['agent_pending'] = None
        st.session_state['agent_previous'] = None
        st.session_state['agent_identity'] = context.identity
    history = st.session_state.setdefault('agent_history',[])
    if not compact:
        st.caption('Continue the same conversation and selected report from Overview.')
        with st.expander('Example questions'):
            st.write('Where can I see occupancy?\n\nWhat is the current report\'s 6-month follow-up coverage?\n\nCompare 6-month and 12-month follow-up coverage in one chart.\n\nGenerate an occupancy and follow-up report.')
    view = 'brief' if compact else 'full'
    with st.container(height=420 if compact else 620,border=not compact,key=f'agent_messages_{view}'):
        if not history:
            st.caption('Ask a question below. Conversation history appears here.')
            if compact:
                st.caption('Try: "What is the 6-month follow-up coverage?" or "Plot monthly referrals, intakes and admissions for 2025."')
        for entry in history:
            with st.chat_message('user'):
                st.text(entry['question'])
            with st.chat_message('assistant'):
                show(entry['reply'],f'agent_{entry["id"]}_{view}',compact=compact)
    prompt = st.chat_input('Ask a question…' if compact else 'Ask about operational metrics...',
                           key='overview_agent' if compact else 'analyst_agent',
                           height=68 if compact else 'content')
    manual = None
    if not compact:
        with st.expander('Advanced · validated JSON specification'):
            text = st.text_area('JSON specification',value='{}',key='agent_spec_editor',height=130)
            if st.button('Run specification',key='agent_run_spec'):
                manual = text
            if st.session_state.get('agent_previous'):
                st.caption('Last validated specification:')
                st.json(st.session_state['agent_previous'])
    if st.button('Clear analyst conversation',key='agent_clear'):
        for name in ('agent_history','agent_pending','agent_previous'):
            st.session_state.pop(name,None)
        st.rerun()
    if prompt or manual is not None:
        request_id = uuid.uuid4().hex
        try:
            with st.spinner('Validating and querying aggregates...'):
                reply = execute_spec(json.loads(manual),context) if manual is not None else handle(
                    prompt,context,st.session_state.get('agent_pending'),st.session_state.get('agent_previous'))
            st.session_state['agent_pending'] = reply.get('pending')
            if reply.get('spec'):
                st.session_state['agent_previous'] = reply['spec']
        except (ValueError,OSError) as exc:
            message = str(exc) if isinstance(exc,ValueError) else 'Local operation failed; no result published.'
            reply = dict(action='error',message=message,identity=context.identity)
        try:
            record(root,context,request_id,reply['action'],reply.get('spec'))
        except OSError:
            reply = dict(action='error',message='Audit write failed; result withheld.',identity=context.identity)
        history.append(dict(id=request_id,question=prompt or '[Validated JSON request]',reply=reply))
        del history[:-8]
        st.rerun()

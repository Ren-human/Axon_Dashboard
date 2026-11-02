"""Compact overview. All summaries use the selected report's existing validation."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from db import numeric
from ui import table, value
from summary_validation import OUTCOME_LABELS, valid_count, outcome_summary, occupancy_summary


def load(name, columns=()):
    try:
        return numeric(table(name), columns)
    except KeyError:
        return pd.DataFrame()


def compact_plot(fig,key,height=235,legend_top=False):
    fig.update_layout(template='plotly_white',height=height,
                      margin=dict(l=8,r=8,t=58 if legend_top else 16,b=28),font=dict(size=12),
                      legend=dict(orientation='h',x=0,y=1.03 if legend_top else -.24,
                                  yanchor='bottom' if legend_top else 'top',font=dict(size=10)))
    st.plotly_chart(fig,width='stretch',key=key)


def make_funnel(data):
    if not {'stage','n'} <= set(data):
        return None,{}
    aliases = {'referral':'Referrals','referrals':'Referrals','intake':'Intakes','intakes':'Intakes',
               'admission':'Admissions','admissions':'Admissions','admitted':'Admissions'}
    work = data.assign(stage_name=data['stage'].astype(str).str.strip().str.lower().map(aliases))
    work = work.dropna(subset=['stage_name'])
    if work['stage_name'].duplicated().any():
        return None,{}
    counts = dict(zip(work['stage_name'],work['n']))
    order = ['Referrals','Intakes','Admissions']
    if any(not valid_count(counts.get(stage)) for stage in order):
        return None,counts
    fig = go.Figure(go.Funnel(y=order,x=[counts[stage] for stage in order],textinfo='value'))
    fig.update_layout(showlegend=False)
    return fig,counts


def make_occupancy(summary):
    if summary is None:
        return None
    view = summary['monthly'].copy()
    dates = pd.to_datetime(view['month'],format='%Y-%m')
    fig = go.Figure()
    fig.add_scatter(x=dates,y=view['occupancy_lower'],name='Known lower',mode='lines+markers')
    fig.add_scatter(x=dates,y=view['occupancy_upper'],name='Possible upper',mode='lines+markers',
                    fill='tonexty',fillcolor='rgba(39,127,142,.12)')
    fig.add_hline(y=1,line_dash='dot',annotation_text='100%',annotation_position='top right')
    fig.update_yaxes(tickformat='.0%',rangemode='tozero')
    fig.update_xaxes(tickformat='%b',dtick='M3')
    return fig


def draw_outcome(summary,issue,months):
    if summary is None:
        st.warning(issue)
        return
    st.caption(f"{months}-month · Residents due: {value(summary['due'])} · Known: {value(summary['known'])}")
    if not summary['due']:
        st.info('No residents due. Coverage and outcome rates are N/A.')
        return
    fig = go.Figure()
    for category,count in summary['counts'].items():
        fig.add_trace(go.Bar(x=[count/summary['due']],y=['All due'],orientation='h',
                            name=OUTCOME_LABELS[category],customdata=[count],
                            hovertemplate='%{fullData.name}: %{customdata:,.0f} (%{x:.1%})<extra></extra>'))
    fig.update_layout(barmode='stack')
    fig.update_xaxes(tickformat='.0%',range=[0,1.03],tickmode='array',tickvals=[0,.25,.5,.75,1])
    compact_plot(fig,f'overview_outcomes_{months}',height=190,legend_top=True)


def render_overview():
    funnel = load('funnel',['n'])
    occupancy = load('monthly_occupancy',['occupancy_lower'])
    outcomes = load('outcomes',['horizon_months','due_n','known_outcome_n',*OUTCOME_LABELS])
    funnel_fig,counts = make_funnel(funnel)
    occupancy_info,occupancy_issue = occupancy_summary(occupancy,table('run_metadata'))
    six,six_issue = outcome_summary(outcomes,6)
    twelve,twelve_issue = outcome_summary(outcomes,12)
    referrals,admissions = counts.get('Referrals'),counts.get('Admissions')
    conversion = (admissions/referrals if valid_count(referrals) and referrals>0 and valid_count(admissions) else float('nan'))
    average = occupancy_info['rate'] if occupancy_info else float('nan')
    coverage = six['coverage'] if six else float('nan')

    with st.container(key='overview_kpis'):
        k1,k2,k3 = st.columns(3,gap='large')
        with k1:
            st.metric('Admission Conversion',value(conversion,percent=True))
            st.caption('Admissions / referrals')
        with k2:
            st.metric('Known Occupancy Lower Bound',value(average,percent=True))
            st.caption('Report period · weighted by available bed-days')
            if not occupancy_info:
                st.warning(occupancy_issue)
            elif not occupancy_info['available']:
                st.info('No available bed-days. Report-period occupancy is N/A.')
        with k3:
            st.metric('6-Month Follow-up Coverage',value(coverage,percent=True))
            if six:
                st.caption(f"Known outcomes / residents due: {value(six['known'])} / {value(six['due'])}")
            else:
                st.caption(six_issue)

    with st.container(key='overview_layout'):
        dashboard,assistant = st.columns([.66,.34],gap='large',vertical_alignment='top')
        with dashboard:
            left,right = st.columns(2,gap='medium')
            with left:
                st.markdown('#### Admission funnel')
                if funnel_fig is not None:
                    compact_plot(funnel_fig,'overview_funnel')
                else:
                    st.info('Funnel unavailable: expected one valid count per stage.')
                st.page_link('pages/funnel.py',label='Explore funnel →')
            with right:
                st.markdown('#### Monthly occupancy')
                occupancy_fig = make_occupancy(occupancy_info)
                if occupancy_fig is not None:
                    compact_plot(occupancy_fig,'overview_occupancy')
                else:
                    st.info(occupancy_issue or 'Monthly occupancy unavailable.')
                st.page_link('pages/occupancy.py',label='Explore occupancy →')

            heading,control = st.columns([1,1],vertical_alignment='center')
            with heading:
                st.markdown('#### Follow-up outcomes')
            with control:
                horizon = st.radio('Follow-up period',[6,12],horizontal=True,
                                   format_func=lambda number:f'{number} Months',
                                   key='overview_followup_period',label_visibility='collapsed')
            summary,issue = (six,six_issue) if horizon==6 else (twelve,twelve_issue)
            draw_outcome(summary,issue,horizon)
            st.caption('All due residents remain in the denominator. Engagement is not verified sobriety.')
            st.page_link('pages/outcomes.py',label='Explore outcomes →')
            with st.expander('Definitions & more analysis'):
                st.write('Occupancy shows known lower / possible upper bounds, not confidence intervals. '
                         'Unknown exits create the interval; rates above 100% are retained. '
                         'The report-period KPI uses total known bed-days / total available bed-days.')
                if occupancy_info:
                    st.caption(f"Occupancy window: {occupancy_info['start']} – {occupancy_info['end']}")
                st.write('Known follow-up outcomes include engagement in recovery and reported relapse. '
                         'Unresolved categories stay in the due denominator. Undated records cannot verify observation timing.')
                a,b = st.columns(2)
                a.page_link('pages/los.py',label='Length of stay →')
                b.page_link('pages/quality.py',label='Data quality →')
        with assistant:
            with st.container(border=True,key='overview_assistant'):
                from agent.presentation import render
                render(compact=True)


render_overview()

"""Executive overview using the selected run supplied by app.py.

Outcomes are wide aggregates from db.py's `outcomes` table, not long-form
`outcomes_summary` rows. Run this page through app.py to retain shared filters.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from db import numeric
from ui import lesson, plot, table, value

from summary_validation import OUTCOME_LABELS, valid_count, outcome_summary, occupancy_summary

def load(name, columns=()):
    """A missing optional table must not prevent the other panels rendering."""
    try:
        return numeric(table(name), columns)
    except KeyError:
        return pd.DataFrame()


def make_funnel(data):
    if not {'stage', 'n'} <= set(data):
        return None, {}
    aliases = {
        'referral': 'Referrals', 'referrals': 'Referrals',
        'intake': 'Intakes', 'intakes': 'Intakes',
        'admission': 'Admissions', 'admissions': 'Admissions', 'admitted': 'Admissions',
    }
    work = data.assign(stage_name=data['stage'].astype(str).str.strip().str.lower().map(aliases))
    work = work.dropna(subset=['stage_name'])
    if work['stage_name'].duplicated().any():
        return None, {}
    counts = dict(zip(work['stage_name'], work['n']))
    order = ['Referrals', 'Intakes', 'Admissions']
    if any(not valid_count(counts.get(stage)) for stage in order):
        return None, counts
    fig = go.Figure(go.Funnel(y=order, x=[counts[stage] for stage in order],
                              textinfo='value'))
    fig.update_layout(height=300, showlegend=False)
    return fig, counts


def make_occupancy(summary):
    if summary is None:
        return None, pd.DataFrame()
    view = summary['monthly'].copy()
    view['_date'] = pd.to_datetime(view['month'], format='%Y-%m')
    fig = go.Figure()
    fig.add_scatter(x=view['_date'], y=view['occupancy_lower'], name='Known lower', mode='lines+markers')
    fig.add_scatter(x=view['_date'], y=view['occupancy_upper'], name='Possible upper', mode='lines+markers',
                    fill='tonexty', fillcolor='rgba(39,127,142,0.15)')
    fig.add_hline(y=1, line_dash='dot', annotation_text='100% capacity')
    fig.update_layout(height=300)
    fig.update_yaxes(tickformat='.0%', title='Capacity used', rangemode='tozero')
    return fig, view


def draw_outcome(summary, issue, months):
    st.markdown(f'**{months}-month follow-up**')
    if summary is None:
        st.warning(issue)
        return
    st.caption(f"Residents due: {value(summary['due'])} · Known outcomes: {value(summary['known'])}")
    if issue:
        st.warning(issue)
    if summary['due'] == 0:
        st.info('No residents due. Coverage and outcome rates are undefined.')
        return
    if summary['counts'] is None:
        return
    fig = go.Figure()
    for category, count in summary['counts'].items():
        fig.add_trace(go.Bar(
            x=[count / summary['due']], y=['All due'], orientation='h',
            name=OUTCOME_LABELS[category], customdata=[count],
            hovertemplate='%{fullData.name}: %{customdata:,.0f} (%{x:.1%})<extra></extra>',
        ))
    fig.update_layout(barmode='stack', height=300, title='Fraction of all residents due' )

    plot(fig, f'overview_outcomes_{months}')


def render_overview():
    st.header('Executive Overview')
    dashboard = st.container()
    with dashboard:
        funnel = load('funnel', ['n'])
        occupancy = load('monthly_occupancy', ['occupancy_lower'])
        outcomes = load('outcomes', ['horizon_months', 'due_n', 'known_outcome_n', *OUTCOME_LABELS])
        funnel_fig, counts = make_funnel(funnel)
        occupancy_info, occupancy_issue = occupancy_summary(occupancy, table('run_metadata'))
        occupancy_fig, monthly = make_occupancy(occupancy_info)
        six, six_issue = outcome_summary(outcomes, 6)
        twelve, twelve_issue = outcome_summary(outcomes, 12)
        referrals, admissions = counts.get('Referrals'), counts.get('Admissions')
        conversion = (admissions / referrals if valid_count(referrals) and referrals > 0
                      and valid_count(admissions) else float('nan'))
        average = occupancy_info['rate'] if occupancy_info else float('nan')
        coverage = six['coverage'] if six is not None else float('nan')

        k1, k2, k3 = st.columns(3)
        with k1:
            st.metric('Admission Conversion', value(conversion, percent=True))
            st.caption('Admissions / referrals')
        with k2:
            st.metric('Report-period Known Occupancy Lower Bound', value(average, percent=True))
            if occupancy_info:
                st.caption(f"{occupancy_info['start']} – {occupancy_info['end']}: sum of known bed-days / sum of available bed-days.")
                if not occupancy_info['available']:
                    st.info('No available bed-days. Report-period occupancy is N/A.')
            else:
                st.warning(occupancy_issue)
        with k3:
            st.metric('6-Month Follow-up Coverage', value(coverage, percent=True))
            if six is not None:
                st.caption(f"Known outcomes / residents due: {value(six['known'])} / {value(six['due'])}")
            else:
                st.caption(six_issue)

        left, right = st.columns(2)
        with left:
            st.subheader('Admission Funnel')
            if funnel_fig is not None:
                plot(funnel_fig, 'overview_funnel')
            else:
                st.info('Funnel unavailable: expected one valid count per referral, intake and admission stage.')
            st.page_link('pages/funnel.py', label='Explore funnel →')
        with right:
            st.subheader('Monthly Occupancy')
            if occupancy_fig is not None:
                plot(occupancy_fig, 'overview_occupancy')
            else:
                st.info(occupancy_issue or 'Monthly occupancy unavailable or ambiguous.')
            st.caption('Known lower / possible upper bounds. Unknown exits create the interval; values above 100% are retained.')
            st.page_link('pages/occupancy.py', label='Explore occupancy →')

        st.subheader('Resident Outcomes')
        c6, c12 = st.columns(2)
        with c6:
            draw_outcome(six, six_issue, 6)
        with c12:
            draw_outcome(twelve, twelve_issue, 12)
        st.caption('Coverage counts engagement in recovery and reported relapse as known outcomes. '
                   'All unresolved categories stay in the due denominator. '
                   'Engagement in recovery is a recorded category, not verified sobriety.')
        st.page_link('pages/outcomes.py', label='Explore outcomes →')

        with st.expander('More analysis'):
            a, b = st.columns(2)
            a.page_link('pages/los.py', label='Length of stay →')
            b.page_link('pages/quality.py', label='Data quality →')
            st.caption('All metrics use the database run selected in the sidebar.')
            st.caption('Outcomes columns available: ' + (', '.join(outcomes.columns) or 'none'))
        #lesson('Six-month coverage is known_outcome_n / due_n from the outcomes table '
         #      '(the pipeline calls this ascertainment_rate). Zero residents due yields N/A. '
          #     'Multiple rows per horizon require an explicit anchor/cohort selection; they are not summed.')

    with st.container():
        from agent.presentation import render
        render()


# Streamlit file pages can execute as __page__ or __main__.
render_overview()

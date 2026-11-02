"""Follow-up details share aggregate validation with Overview."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui import table, value
from summary_validation import outcome_summary

head, switch = st.columns([3, 2], vertical_alignment='center')
with head:
    st.subheader('Recovery Outcomes')
with switch:
    horizon = st.radio('Follow-up period', [6, 12], horizontal=True,
                       format_func=lambda x: f'{x} Months', label_visibility='collapsed')
st.caption('Outcome rates are based on all eligible residents due for follow-up.')
frame = table('outcomes')
summary, issue = outcome_summary(frame, horizon)
if issue:
    st.warning(issue)
if summary is not None:
    due, known, counts, row = summary['due'], summary['known'], summary['counts'], summary['row']
    kpi_left, kpi_right = st.columns(2)
    with kpi_left:
        st.metric('Eligible Residents', value(due))
    with kpi_right:
        st.metric('Follow-up Coverage', value(summary['coverage'], percent=True))
    st.caption(f'Known outcomes / all residents due: {value(known)} / {value(due)}. '
               'Source: known_outcome_n / due_n = ascertainment_rate.')
    if due:
        fig = go.Figure()
        for name, key, color in [('Engaged in recovery', 'engaged_in_recovery', '#0d8bff'),
                                  ('Relapse reported', 'relapse_reported', '#934cf3'),
                                  ('Lost to follow-up', 'lost_to_follow_up', '#ff6926')]:
            fig.add_trace(go.Bar(x=[name], y=[counts[key]], name=name, marker_color=color,
                                 hovertemplate=f'{name}: %{{y:,.0f}} residents<extra></extra>', showlegend=False))
        fig.update_layout(height=345, margin=dict(l=10, r=10, t=12, b=12), bargap=0.24,
                          xaxis_title=None, yaxis_title='Residents',
                          yaxis=dict(rangemode='tozero', gridcolor='rgba(128,128,128,0.15)'),
                          plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, width='stretch', key='recovery_outcomes')
        st.caption(f'Denominator: {value(due)} eligible residents due for {horizon}-month follow-up.')
        other = {k: counts[k] for k in ('unknown', 'missing', 'due_but_marked_not_yet_due', 'unrecognized') if counts[k]}
        if other:
            st.info('Additional outcome categories (not included in the three bars): ' +
                    ', '.join(f'{k.replace("_", " ")}: {v:g}' for k, v in other.items()))
    else:
        st.info('No residents due. Coverage and outcome rates are N/A.')
    bounds = ['recovery_fraction_all_due_lower', 'recovery_fraction_all_due_upper']
    if all(c in row.index for c in bounds):
        st.caption('Recovery sensitivity bounds (worst/best scenarios, not confidence intervals): ' +
                   ' – '.join(value(pd.to_numeric(row[c], errors='coerce'), percent=True) for c in bounds))
st.caption('Engagement is a recorded category, not verified sobriety. Known outcomes include '
           'engaged in recovery + relapse reported. Undated follow-up records cannot verify observation timing.')
with st.expander('Source data and calculation notes'):
    st.dataframe(frame, width='stretch')

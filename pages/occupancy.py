import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui import plot, raw, table
from summary_validation import occupancy_summary, occupancy_label, occupancy_quality_note

st.header('Monthly occupancy')
st.write('Documented bed-days as a share of available bed-days.')
frame = table('monthly_occupancy')
summary, issue = occupancy_summary(frame, table('run_metadata'))
if issue:
    st.warning(issue)
elif summary:
    view = summary['monthly'].copy()
    view['_month'] = pd.to_datetime(view['month'], format='%Y-%m')
    months = view['month'].tolist()
    start, end = st.select_slider('Displayed month window', options=months, value=(months[0], months[-1]))
    view = view[view['month'].between(start, end)]
    fig = go.Figure()
    fig.add_scatter(x=view['_month'], y=view['occupancy_lower'],
                    name=occupancy_label(summary), mode='lines+markers')
    fig.add_hline(y=1, line_dash='dot', annotation_text='100% capacity')
    fig.update_yaxes(title='Bed utilization · fraction of available bed-days', tickformat='.0%', rangemode='tozero')
    plot(fig, 'occupancy_detail')
st.caption(occupancy_quality_note(summary))
st.caption('Active stays count through the effective reporting cutoff (as_of), inclusive. '
           'Dated stays use [admission, discharge); discharge day is excluded. '
           'Exited records without a usable discharge date are not treated as active. '
           'Partial months use observed days; values above 100% are retained. '
           'Recorded zeros do not prove an empty building.')
st.page_link('pages/quality.py', label='Data quality & occupancy methodology →')
raw(frame.drop(columns=[c for c in frame if c.endswith('_upper') or c in
                       ('occupancy_upper', 'upper_exceeds_capacity', 'uncertain_bed_days')]),
    'monthly_occupancy')

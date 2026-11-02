import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui import plot, raw, table
from summary_validation import occupancy_summary

st.header('Monthly occupancy')
st.write('Known lower and possible upper occupancy; uncertain exits create the interval.')
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
    fig.add_scatter(x=view['_month'], y=view['occupancy_lower'], name='Known lower', mode='lines+markers')
    fig.add_scatter(x=view['_month'], y=view['occupancy_upper'], name='Possible upper',
                    mode='lines+markers', fill='tonexty', fillcolor='rgba(39,127,142,0.15)')
    fig.add_hline(y=1, line_dash='dot', annotation_text='100% capacity')
    fig.update_yaxes(title='Occupancy · fraction of available bed-days', tickformat='.0%', rangemode='tozero')
    plot(fig, 'occupancy_detail')
st.caption('Rates are stored as fractions. Bounds are not confidence intervals. Values above 100% are retained. '
           'Partial months use observed days; recorded zeros do not prove an empty building.')
raw(frame, 'monthly_occupancy')

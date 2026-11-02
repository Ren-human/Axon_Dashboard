import plotly.express as px
import streamlit as st

from db import numeric
from ui import lesson, plot, raw, require, table

st.header('Length of stay')
st.write('Ended stays, ongoing elapsed stays, and the completed-program subset are separate cohorts.')
frame = numeric(table('los'), ['median_days', 'p90_days', 'n'])
if require(frame, ['cohort', 'median_days'], 'LOS'):
    options = frame['cohort'].dropna().astype(str).unique().tolist()
    chosen = st.multiselect('LOS cohorts', options, default=options)
    view = frame[frame['cohort'].astype(str).isin(chosen)]
    measures = [c for c in ['median_days', 'p90_days'] if c in view]
    if view['cohort'].duplicated().any():
        st.warning('Multiple rows per cohort: refine source dimensions before comparing statistics.')
    elif not view.empty:
        # Plotly Express likes "long" data: one row per cohort/statistic.
        long = view.melt(id_vars='cohort', value_vars=measures, var_name='Statistic', value_name='Days')
        plot(px.bar(long, x='cohort', y='Days', color='Statistic', barmode='group'), 'los_detail')
st.caption('Ongoing LOS is right-censored elapsed time, not a prediction of eventual stay length. '
           'These summary tables cannot support a resident-level histogram or survival curve.')
raw(frame, 'los')
#lesson('Inspect the output of `DataFrame.melt()` to see how two numeric columns become grouped bars. '
 #      'Keep `n` visible in the raw table: a median without its cohort size is difficult to interpret.')

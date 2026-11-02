"""Plotly graph_objects gives direct control over a funnel trace."""
import plotly.graph_objects as go
import streamlit as st

from db import numeric
from ui import lesson, plot, raw, require, table

st.header('Referral funnel')
st.write('Verified milestone sequence for the referral cohort. Discharge is a supplementary stage.')
frame = numeric(table('funnel'), ['n'])
if require(frame, ['stage', 'n'], 'Funnel'):
    # Keep database ordering. Allow learners to explicitly choose/reorder stages.
    stages = frame['stage'].dropna().astype(str).drop_duplicates().tolist()
    chosen = st.multiselect('Stages to display · in selected order', stages, default=stages)
    view = frame[frame['stage'].astype(str).isin(chosen)].copy()
    view['_order'] = view['stage'].astype(str).map({s: i for i, s in enumerate(chosen)})
    view = view.sort_values('_order')
    if view['stage'].duplicated().any():
        st.warning('Multiple rows per stage: select one run or refine the source; no automatic summation.')
    elif not view.empty:
        if (view['n'].diff().dropna() > 0).any():
            st.warning('Counts increase in this order. Verify stage order and cohort definitions.')
        # Do not use percent-previous of DISPLAYED stages: filtering would change its meaning.
        fig = go.Figure(go.Funnel(y=view['stage'], x=view['n'], textinfo='value',
                                 marker=dict(color='#277f8e')))
        fig.update_layout(xaxis_title='Residents')
        plot(fig, 'funnel_detail')
    st.caption('Conversions in the source table retain their original denominators when stages are hidden. '
               'Missing intake can exclude a recorded admission from this strict funnel.')
raw(frame, 'funnel')
st.page_link('pages/occupancy.py', label='Next: occupancy →')
#lesson('Edit `go.Funnel(y=..., x=...)` to understand chart inputs. '
 #      'The multiselect filters only this chart; it does not recompute the referral cohort. '
 #      'Keep stage order explicit instead of sorting counts to make a funnel look tidy.')

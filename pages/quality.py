import plotly.express as px
import streamlit as st

from db import numeric
from ui import plot, raw, table

st.header('Data quality review')
st.write('Flags by rule and severity help explain uncertainty in the operational metrics.')
frame = numeric(table('data_quality_summary'), ['n'])
view = frame.copy()
problem = st.session_state.get('problems', {}).get('data_quality_summary')
if problem:
    st.error(f'质量汇总读取失败，无法判断是否存在质量问题：{problem}')
elif not {'severity', 'rule', 'n'} <= set(frame):
    st.error('质量汇总结构无效：需要 severity, rule, n，无法判断是否存在质量问题。')
elif frame.empty:
    st.success('没有质量标记（质量汇总已成功读取）。')
else:
    from summary_validation import valid_count
    if not all(valid_count(n) for n in frame['n']):
        st.error('质量计数无效，图表已停止展示。')
    else:
        options = frame['severity'].dropna().astype(str).unique().tolist()
        selected = st.multiselect('Severity', options, default=options)
        view = frame[frame['severity'].astype(str).isin(selected)]
        if not view.empty:
            plot(px.bar(view.sort_values('n'), x='n', y='rule', orientation='h', color='severity',
                        labels={'n': 'Flag count', 'rule': 'Rule'}), 'quality_detail')
st.caption('A resident may trigger multiple rules. Counts are flags, not unique affected residents. '
           'Review flags may describe reporting-cutoff conflicts rather than source errors.')
if not problem:
    raw(view, 'data_quality_summary')

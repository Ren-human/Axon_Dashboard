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


st.subheader('Occupancy methodology & uncertainty')
st.write('Confirmed Bed Utilization includes valid dated stays and stays recorded as active '
         'with no conflicting or invalid exit date, through the effective report cutoff (as_of). '
         'A valid discharge after the cutoff also confirms presence through that cutoff. '
         'Admission day counts; discharge day does not. The cutoff day counts for open stays. '
         'The denominator is bed capacity × observed calendar days; period totals use bed-day weights.')
st.write('Discharged, alumni and aftercare records without a usable exit date are unresolved, '
         'not active. Active records with an invalid exit date are also unresolved. '
         'Negative stay intervals, missing admissions and duplicate or missing IDs are excluded. '
         'Confirmed is conditional on the recorded dates, active status and constant capacity being correct; '
         'it is a conservative contribution from usable records, not an unbiased estimate of actual occupancy. '
         'The snapshot status cannot independently verify historical status. Imported reports without '
         'confirmed-stay provenance are labelled Recorded Bed Utilization.')
st.caption('There is no opening resident register. Missing admissions and excluded identities fall '
           'outside the calculated interval, so neither endpoint bounds whole-building occupancy.')
with st.expander('Unknown-exit sensitivity (not an operational KPI)'):
    st.write('The possible upper scenario adds every potential bed-day from unresolved exits through '
             'the cutoff. It is conditional on usable admissions, may exceed capacity, and is neither '
             'a confidence interval nor a credible estimate of actual occupancy. No missing dates are imputed.')
    from summary_validation import occupancy_summary
    occupancy, occupancy_issue = occupancy_summary(table('monthly_occupancy'), table('run_metadata'))
    if occupancy_issue:
        st.warning(occupancy_issue)
    elif occupancy:
        monthly = occupancy['monthly']
        columns = [c for c in ('month', 'known_bed_days_lower', 'uncertain_bed_days',
                              'bed_days_upper', 'available_bed_days', 'occupancy_lower',
                              'occupancy_upper') if c in monthly]
        raw(monthly[columns], 'occupancy_uncertainty')

"""Entry UI only. Candidate writing/calculation/publication live in report_versions."""
from datetime import date
import pandas as pd
import streamlit as st

import metrics
import report_versions as versions

st.header('Add Resident Record')
st.caption('For local, single-user use. Preview the record and review quality warnings before confirming. Blank dates remain blank.')
try:
    cfg = versions.load_config()
    manifest, _, _, _, headers = versions.source_snapshot(cfg)
except (OSError, ValueError, KeyError) as exc:
    st.warning(str(exc))
    st.code('python report_versions.py initialize --config report_config.json', language='powershell')
    st.button('Preview Record', disabled=True)
    st.button('Confirm Submission', disabled=True)
    st.stop()

raw_path, target_db = versions.active_paths(cfg, manifest)
st.info(f'Recording target: {raw_path}\n\nActive version: {manifest["version"]}; report cutoff: {manifest["report_as_of"]}')
st.caption(f'Currently viewing report: {st.session_state.get("db_path", "None selected")}')
st.json(cfg['report'], expanded=False)
st.caption('The as_of value is the source snapshot cutoff. The effective report cutoff is the earlier of that date and fiscal year-end. Adding a record does not change these parameters.')
if st.session_state.get('publish_success'):
    result = st.session_state['publish_success']
    receipt = result['receipt']
    st.success(f'Resident {receipt["resident_id"]} was submitted and calculated successfully. Record version: {receipt["version"]};'
               f'Active version: {result["active"]["version"]}; report cutoff: {receipt["report_as_of"]}.')
if st.session_state.get('publish_error'):
    st.error(st.session_state['publish_error'])

busy = st.session_state.get('publish_busy', False)
draft = {}
left, right = st.columns(2)
with left:
    draft['resident_id'] = st.text_input('Resident ID (required)', key='entry_resident_id', disabled=busy)
    labels = {'referral_date': 'Referral date', 'intake_date': 'Intake date',
              'admission_date': 'Admission date', 'discharge_date': 'Discharge date'}
    for field, label in labels.items():
        d = st.date_input(label + ' (optional)', value=None, min_value=date(1, 1, 1),
                          max_value=date(9998, 12, 31), key='entry_' + field, disabled=busy)
        draft[field] = d.isoformat() if d else ''
    draft['current_status'] = st.selectbox('Current status', ['', 'not_admitted', 'phase_1', 'phase_2',
                                                        'phase_3', 'discharged', 'alumni', 'aftercare'],
                                           key='entry_current_status', disabled=busy,
                                           help='May be left blank; the calculation will flag the missing status.')
    draft['discharge_reason'] = st.text_input('Discharge reason (optional)', key='entry_discharge_reason', disabled=busy,
                                             help='Enter the source description. The value completed is counted separately as program completion.')
with right:
    draft['entrance_fee'] = st.text_input('Entrance fee (optional)', key='entry_entrance_fee', disabled=busy,
                                         help='Enter a finite, non-negative number. A blank value is not changed to zero.')
    draft['fee_waived'] = st.selectbox('Fee waived', ['', 'true', 'false'], key='entry_fee_waived', disabled=busy,
                                      format_func=lambda x: {'': 'Not recorded', 'true': 'Yes', 'false': 'No'}[x])
    for horizon in (6, 12):
        field = f'followup_{horizon}m'
        draft[field] = st.selectbox(f'{horizon}-month follow-up outcome', ['', 'engaged_in_recovery', 'relapse_reported',
                                   'lost_to_follow_up', 'unknown', 'not_yet_due'], key='entry_' + field,
                                   disabled=busy, help='A blank value means not recorded. Engagement does not mean verified sobriety.')
    draft['staff_note'] = st.text_area('Staff note (optional)', key='entry_staff_note', disabled=busy)
    draft['bed_capacity'] = str(cfg['report']['capacity'])
    st.text_input('Report bed capacity (from confirmed settings)', value=draft['bed_capacity'], disabled=True)
extras = [c for c in headers if c not in metrics.REQUIRED]
if extras:
    st.caption('Existing extra columns are preserved; these columns will be blank for the new record: ' + ', '.join(extras))

signature = versions.digest(draft)
if st.session_state.get('entry_preview_signature') != signature:
    st.session_state.pop('entry_preview', None)
if st.button('Preview Record', disabled=busy):
    st.session_state.pop('publish_success', None)
    st.session_state.pop('publish_error', None)
    try:
        st.session_state['entry_preview'] = versions.preview_record(cfg, draft)
        st.session_state['entry_preview_signature'] = signature
    except (OSError, ValueError) as exc:
        st.session_state.pop('entry_preview', None)
        st.error(f'Input was not saved: {exc}')

preview = st.session_state.get('entry_preview')
if preview:
    st.subheader('Review Preview')
    st.dataframe(pd.DataFrame([preview['record']]), hide_index=True)
    st.caption('The preview uses the report settings shown above. If you change any field, preview the record again.')
    if preview['warnings']:
        st.warning('The following pipeline quality warnings are advisory. You may keep the record; confirming indicates that you have reviewed them.')
        st.dataframe(pd.DataFrame(preview['warnings'])[['rule', 'severity', 'explanation']], hide_index=True)
    else:
        st.info('No quality warnings were raised for this new record.')
    if st.button('Confirm Submission', disabled=busy):
        st.session_state['publish_busy'] = True
        st.rerun()
else:
    st.button('Confirm Submission', disabled=True)

if busy and preview:
    try:
        with st.spinner('Preparing candidate data, calculating metrics, importing and validating the report. The new version will be activated if all steps succeed…'):
            result = versions.submit_record(cfg, preview)
        st.session_state['publish_success'] = result
        st.session_state.pop('publish_error', None)
        st.session_state.pop('entry_preview', None)
        st.session_state['switch_to_active'] = True
        st.cache_data.clear()
    except Exception as exc:
        # Keep all field widgets and preview for retry; never label a candidate as saved.
        st.session_state['publish_error'] = str(exc)
    finally:
        st.session_state['publish_busy'] = False
    st.rerun()

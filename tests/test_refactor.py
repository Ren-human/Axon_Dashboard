"""Synthetic integration/UI tests; never append to the configured real CSV."""
from concurrent.futures import ThreadPoolExecutor
import copy
import csv
from datetime import date
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb
import pandas as pd
from streamlit.testing.v1 import AppTest
import db
import duckdb_store
import metrics
import report_versions as versions
from summary_validation import OUTCOME_LABELS, outcome_summary, occupancy_summary


def raw_record(rid='BASE', **values):
    row = {k: '' for k in metrics.REQUIRED}
    row.update(resident_id=rid, referral_date='2025-01-01', current_status='not_admitted', bed_capacity='2')
    row.update(values)
    return row


def write_csv(path, records):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='test-', dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.seed = self.root / 'seed.csv'
        write_csv(self.seed, [raw_record(' BASE ', extra=' retain spaces  ', staff_note='one\ntwo')])
        self.seed_bytes = self.seed.read_bytes()
        self.config_path = self.root / 'config.json'
        self.config_path.write_text(json.dumps(dict(source_csv=str(self.seed),
            version_root=str(self.root / 'versions'), report=dict(as_of='2025-02-10', fiscal_year=2025,
            capacity=2, followup_anchor='discharge', occupancy_start='2025-01-01'))), encoding='utf-8')
        self.cfg = versions.load_config(self.config_path)
        self.initial = versions.initialize(self.cfg)
        self.initial_raw, self.initial_db = versions.active_paths(self.cfg, self.initial)
        self.initial_db_hash = versions.file_hash(self.initial_db)

    def draft(self, rid='NEW', **kw):
        return raw_record(rid, **kw)

    def assert_initial_untouched(self):
        self.assertEqual(self.seed.read_bytes(), self.seed_bytes)
        self.assertEqual(versions.file_hash(self.initial_db), self.initial_db_hash)

    def app(self, database=None, config=None):
        env = dict(HARBOURVIEW_CONFIG=str(config or self.config_path),
                   HARBOURVIEW_DB=str(database or self.initial_db))
        context = patch.dict(os.environ, env)
        context.start()
        self.addCleanup(context.stop)
        return AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()


class PublicationTests(Fixture):
    def test_full_pipeline_six_tables_and_empty_quality(self):
        frames, problems = db.load(self.initial_db)
        self.assertEqual(problems, {})
        self.assertEqual(set(frames), set(db.TABLES))
        self.assertEqual(list(frames['data_quality_summary']), ['severity', 'rule', 'n'])
        self.assertTrue(frames['data_quality_summary'].empty)
        output = versions.version_dir(self.cfg, self.initial['version']) / 'aggregates'
        duckdb_store.validate_database(self.initial_db, output)
        meta = frames['run_metadata'].iloc[0]
        self.assertEqual(meta['input_sha256'], versions.file_hash(self.initial_raw))
        self.assertEqual(meta['metrics_version'], metrics.METRICS_VERSION)
        self.assertEqual(meta['as_of'], '2025-02-10')
        with duckdb.connect(str(self.initial_db), read_only=True) as con:
            self.assertEqual(len(con.execute('SHOW TABLES').fetchall()), 6)

    def test_success_preview_commit_preserves_data_and_parameters(self):
        preview = versions.preview_record(self.cfg, self.draft())
        self.assertEqual(preview['warnings'], [])
        self.assertEqual(versions.current(self.cfg), self.initial)
        result = versions.submit_record(self.cfg, preview)
        active = versions.current(self.cfg)
        self.assertEqual(active, result['active'])
        self.assertEqual(active['params'], self.cfg['report'])
        self.assertEqual(active['report_as_of'], '2025-02-10')
        self.assertNotEqual(active['version'], self.initial['version'])
        source, database = versions.active_paths(self.cfg, active)
        _, original, normalized, headers = versions.read_raw(source)
        self.assertEqual(len(original), 2)
        self.assertEqual(original[0]['resident_id'], ' BASE ')
        self.assertEqual(original[0]['extra'], ' retain spaces  ')
        self.assertEqual(original[0]['staff_note'], 'one\ntwo')
        self.assertEqual(original[1]['extra'], '')
        for c in ('intake_date', 'admission_date', 'discharge_date'):
            self.assertEqual(original[1][c], '')
        frames, problems = db.load(database)
        self.assertFalse(problems)
        self.assertEqual(frames['run_metadata'].iloc[0]['input_rows'], 2)
        self.assertEqual(frames['funnel'].iloc[0]['n'], 2)
        self.assert_initial_untouched()

    def test_duplicate_and_invalid_inputs_block_preview(self):
        invalid = [dict(resident_id=' BASE '), dict(resident_id='  '), dict(entrance_fee='nan'),
                   dict(entrance_fee='inf'), dict(entrance_fee='-1'), dict(entrance_fee='abc'),
                   dict(admission_date='2025-02-30'), dict(followup_6m='guess'),
                   dict(current_status='other'), dict(fee_waived='maybe'), dict(bed_capacity='3')]
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                versions.preview_record(self.cfg, self.draft(**fields))
        self.assertEqual(versions.current(self.cfg), self.initial)

    def test_quality_warnings_are_preserved_not_blocked(self):
        preview = versions.preview_record(self.cfg, self.draft(referral_date='2025-01-10',
            intake_date='2025-01-05', admission_date='2025-01-06', current_status='phase_1',
            entrance_fee='100', fee_waived='true'))
        rules = {r['rule'] for r in preview['warnings']}
        self.assertIn('NEGATIVE_REFERRAL_TO_INTAKE', rules)
        self.assertIn('WAIVED_WITH_POSITIVE_FEE', rules)
        result = versions.submit_record(self.cfg, preview)
        self.assertEqual(result['receipt']['resident_id'], 'NEW')

    def test_repeated_submission_and_old_receipt_do_not_duplicate_or_revert(self):
        first = versions.preview_record(self.cfg, self.draft())
        published = versions.submit_record(self.cfg, first)
        replay = versions.submit_record(self.cfg, first)
        self.assertTrue(replay['already_applied'])
        self.assertEqual(replay['active'], published['active'])
        versions.submit_record(self.cfg, versions.preview_record(self.cfg, self.draft('THIRD')))
        newest = versions.current(self.cfg)
        replay = versions.submit_record(self.cfg, first)
        self.assertEqual(replay['active'], newest)
        self.assertEqual(versions.current(self.cfg), newest)
        raw, _ = versions.active_paths(self.cfg, newest)
        self.assertEqual(len(versions.read_raw(raw)[1]), 3)

    def test_stale_preview_and_tampered_preview_require_new_preview(self):
        stale = versions.preview_record(self.cfg, self.draft('LATER'))
        fresh = versions.preview_record(self.cfg, self.draft())
        changed = copy.deepcopy(fresh)
        changed['record']['staff_note'] = 'changed after preview'
        with self.assertRaisesRegex(ValueError, '预览'):
            versions.submit_record(self.cfg, changed)
        versions.submit_record(self.cfg, fresh)
        with self.assertRaisesRegex(ValueError, '重新预览'):
            versions.submit_record(self.cfg, stale)

    def test_config_change_requires_new_preview(self):
        preview = versions.preview_record(self.cfg, self.draft())
        changed = copy.deepcopy(self.cfg)
        changed['report']['as_of'] = '2025-02-11'
        with self.assertRaisesRegex(ValueError, '重新预览'):
            versions.submit_record(changed, preview)
        self.assertEqual(versions.current(self.cfg), self.initial)

    def test_failure_stages_preserve_pointer_and_allow_retry(self):
        preview = versions.preview_record(self.cfg, self.draft())
        for module, name, stage in ((metrics, 'calculate_file', '计算'),
                                     (metrics, 'export_result', '导出汇总'),
                                     (duckdb_store, 'build', '导入 DuckDB'),
                                     (duckdb_store, 'validate_database', '校验新数据库')):
            with self.subTest(stage=stage):
                with patch.object(module, name, side_effect=RuntimeError('injected failure')):
                    with self.assertRaises(versions.PublicationError) as caught:
                        versions.submit_record(self.cfg, preview)
                self.assertEqual(caught.exception.stage, stage)
                self.assertEqual(versions.current(self.cfg), self.initial)
                self.assert_initial_untouched()
        result = versions.submit_record(self.cfg, preview)
        self.assertEqual(result['receipt']['resident_id'], 'NEW')

    def test_atomic_activation_failure_preserves_current(self):
        preview = versions.preview_record(self.cfg, self.draft())
        original_replace = versions.os.replace
        def fail_pointer(src, dst):
            if Path(dst).name == 'current.json':
                raise PermissionError('injected activation failure')
            return original_replace(src, dst)
        with patch.object(versions.os, 'replace', side_effect=fail_pointer):
            with self.assertRaises(versions.PublicationError) as caught:
                versions.submit_record(self.cfg, preview)
        self.assertEqual(caught.exception.stage, '启用版本')
        self.assertEqual(versions.current(self.cfg), self.initial)
        self.assert_initial_untouched()
        versions.submit_record(self.cfg, preview)

    def test_parallel_confirmation_is_serialized(self):
        preview = versions.preview_record(self.cfg, self.draft())
        started, proceed = threading.Event(), threading.Event()
        original = metrics.calculate_file
        def blocked(*args, **kwargs):
            started.set()
            if not proceed.wait(10):
                raise RuntimeError('test timeout')
            return original(*args, **kwargs)
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(metrics, 'calculate_file', side_effect=blocked):
            future = pool.submit(versions.submit_record, self.cfg, preview)
            try:
                self.assertTrue(started.wait(10))
                with self.assertRaisesRegex(ValueError, '发布操作'):
                    versions.submit_record(self.cfg, preview)
            finally:
                proceed.set()
            result = future.result(timeout=15)
        self.assertEqual(result['receipt']['resident_id'], 'NEW')
        raw, _ = versions.active_paths(self.cfg, versions.current(self.cfg))
        self.assertEqual(len(versions.read_raw(raw)[1]), 2)

    def test_existing_databases_and_initialization_are_never_overwritten(self):
        with self.assertRaises(ValueError):
            versions.initialize(self.cfg)
        source = versions.version_dir(self.cfg, self.initial['version']) / 'aggregates'
        with self.assertRaises(FileExistsError):
            duckdb_store.build(source, self.initial_db)
        self.assert_initial_untouched()

    def test_source_tampering_blocks_submission(self):
        preview = versions.preview_record(self.cfg, self.draft())
        self.initial_raw.write_bytes(self.initial_raw.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, '哈希'):
            versions.submit_record(self.cfg, preview)
        self.assertEqual(versions.current(self.cfg), self.initial)


class AggregateTests(unittest.TestCase):
    def outcome(self):
        rows = [dict(raw_record(str(i), admission_date='2024-01-01', discharge_date='2024-02-01',
                               current_status='discharged', discharge_reason='completed', followup_6m=value), _row=i+2)
                for i, value in enumerate(('engaged_in_recovery', 'relapse_reported', 'lost_to_follow_up', 'unknown'))]
        result = metrics.calculate(rows, date(2025, 2, 10), capacity=2, start=date(2025, 1, 1), fiscal_year=2025)
        return pd.DataFrame(result['outcomes'])

    def test_followup_counts_and_all_stored_rates_are_checked(self):
        frame = self.outcome()
        summary, issue = outcome_summary(frame, 6)
        self.assertFalse(issue)
        self.assertEqual(summary['coverage'], 0.5)
        for col, val in [('due_n', -1), ('due_n', 1.5), ('known_outcome_n', 5),
                         ('known_outcome_n', float('inf')), ('missing', -1), ('missing', 0.5),
                         ('missing', 1), ('engaged_in_recovery', 0), ('ascertainment_rate', 0.8),
                         ('recovery_fraction_all_due_upper', 0.1)]:
            bad = frame.copy().astype({col: 'float64'})
            bad.loc[0, col] = val
            with self.subTest(col=col, value=val):
                summary, issue = outcome_summary(bad, 6)
                self.assertIsNone(summary)
                self.assertTrue(issue)
        self.assertIsNone(outcome_summary(frame.drop(columns='known_outcome_n'), 6)[0])
        self.assertIsNone(outcome_summary(pd.concat([frame, frame.iloc[[0]]]), 6)[0])

    def test_followup_zero_denominator_requires_null_rates(self):
        result = metrics.calculate([dict(raw_record(), _row=2)], date(2025, 2, 10), capacity=2)
        frame = pd.DataFrame(result['outcomes'])
        summary, issue = outcome_summary(frame, 6)
        self.assertFalse(issue)
        self.assertTrue(math.isnan(summary['coverage']))
        frame['ascertainment_rate'] = 0.0
        self.assertIsNone(outcome_summary(frame, 6)[0])

    def occupancy(self):
        row = dict(raw_record(admission_date='2025-01-31', current_status='phase_1'), _row=2)
        result = metrics.calculate([row], date(2025, 2, 10), capacity=2,
                                   start=date(2025, 1, 15), fiscal_year=2025)
        return pd.DataFrame(result['monthly_occupancy']), pd.DataFrame([result['metadata']])

    def test_occupancy_uses_partial_month_bed_day_weights(self):
        frame, meta = self.occupancy()
        summary, issue = occupancy_summary(frame, meta)
        self.assertFalse(issue)
        self.assertAlmostEqual(summary['rate'], 11 / 54)
        self.assertNotAlmostEqual(summary['rate'], frame['occupancy_lower'].mean())

    def test_occupancy_missing_invalid_and_duplicate_months_are_not_dropped(self):
        frame, meta = self.occupancy()
        variants = [frame.iloc[:1], pd.concat([frame, frame.iloc[[0]]]), frame.drop(columns='known_bed_days_lower')]
        for col, value in [('available_bed_days', -1), ('known_bed_days_lower', float('inf')),
                           ('month', 'bad'), ('occupancy_lower', 0.9)]:
            bad = frame.copy()
            if col != 'month':
                bad[col] = bad[col].astype(float)
            bad.loc[0, col] = value
            variants.append(bad)
        for bad in variants:
            self.assertIsNone(occupancy_summary(bad, meta)[0])

    def test_occupancy_zero_denominator_is_na_and_over_capacity_is_retained(self):
        frame, meta = self.occupancy()
        frame[['available_bed_days', 'known_bed_days_lower', 'uncertain_bed_days', 'bed_days_upper']] = 0
        frame[['occupancy_lower', 'occupancy_upper']] = float('nan')
        summary, issue = occupancy_summary(frame, meta)
        self.assertFalse(issue)
        self.assertTrue(math.isnan(summary['rate']))
        rows = [dict(raw_record(str(i), admission_date='2025-01-01', current_status='phase_1'), _row=i+2) for i in range(3)]
        result = metrics.calculate(rows, date(2025, 1, 10), capacity=2, start=date(2025, 1, 1))
        summary, issue = occupancy_summary(pd.DataFrame(result['monthly_occupancy']), pd.DataFrame([result['metadata']]))
        self.assertFalse(issue)
        self.assertEqual(summary['rate'], 1.5)


class UITests(Fixture):
    def setUp(self):
        super().setUp()
        # AppTest recreates PagesManager and resets its navigation mode each run.
        # With a pages/ folder, its legacy auto-discovery can bypass app.py on
        # switch_page(). Keep the production st.navigation mode for these tests.
        from streamlit.runtime.pages_manager import PagesManager
        original = PagesManager.__init__
        def initialize_navigation(manager, *args, **kwargs):
            original(manager, *args, **kwargs)
            PagesManager.uses_pages_directory = False
        navigation = patch.object(PagesManager, '__init__', initialize_navigation)
        navigation.start()
        self.addCleanup(navigation.stop)

    def assert_clean(self, app):
        self.assertEqual(len(app.exception), 0, [x.message for x in app.exception])

    def button(self, app, label):
        # The supplied production UI now uses English labels; accept either locale.
        labels = {label, {'预览记录': 'Preview Record', '确认提交': 'Confirm Submission',
                         '浏览录入数据源的当前启用报告': 'Open the active report for resident entry'}.get(label, label)}
        return next(b for b in app.button if b.label in labels)

    def test_all_pages_and_reruns_do_not_compute(self):
        with patch.object(metrics, 'calculate_file', side_effect=AssertionError('unexpected full calculation')):
            app = self.app()
            self.assert_clean(app)
            for page in ('funnel', 'occupancy', 'los', 'outcomes', 'quality', 'add_resident', 'overview'):
                app.switch_page(f'pages/{page}.py').run()
                self.assert_clean(app)
            app.chat_input[0].set_value('status').run()
            self.assert_clean(app)
            self.button(app, 'Reload database').click().run()
            self.assert_clean(app)

    def test_empty_quality_is_success_and_failed_read_is_error(self):
        app = self.app().switch_page('pages/quality.py').run()
        self.assert_clean(app)
        self.assertTrue(any('没有质量标记' in x.value for x in app.success))
        copied = self.root / 'bad-quality.duckdb'
        shutil.copyfile(self.initial_db, copied)
        with duckdb.connect(str(copied)) as con:
            con.execute('DROP TABLE data_quality_summary')
        app.text_input(key='report_db').set_value(str(copied)).run()
        self.assert_clean(app)
        self.assertTrue(any('读取失败' in x.value for x in app.error))
        self.assertFalse(any('没有质量标记' in x.value for x in app.success))

    def test_unconfigured_source_disables_entry_analysis_still_works(self):
        app = self.app(config=self.root / 'missing.json')
        self.assert_clean(app)
        self.assertTrue(len(app.metric))
        app.switch_page('pages/add_resident.py').run()
        self.assert_clean(app)
        self.assertTrue(self.button(app, '预览记录').disabled)
        self.assertTrue(self.button(app, '确认提交').disabled)

    def test_missing_source_and_uninitialized_source_disable_entry(self):
        cfg = json.loads(self.config_path.read_text())
        cfg['version_root'] = str(self.root / 'uninitialized')
        cfg['source_csv'] = str(self.root / 'missing.csv')
        self.config_path.write_text(json.dumps(cfg), encoding='utf-8')
        app = self.app().switch_page('pages/add_resident.py').run()
        self.assert_clean(app)
        self.assertTrue(self.button(app, '确认提交').disabled)

    def test_entry_preview_edit_failure_retry_and_success_refresh(self):
        app = self.app().switch_page('pages/add_resident.py').run()
        self.assert_clean(app)
        for widget in app.date_input:
            self.assertIsNone(widget.value)
        app.text_input(key='entry_resident_id').set_value('UI-NEW').run()
        app.selectbox(key='entry_current_status').set_value('not_admitted').run()
        self.button(app, '预览记录').click().run()
        self.assert_clean(app)
        self.assertFalse(self.button(app, '确认提交').disabled)
        app.text_area(key='entry_staff_note').set_value('changed after preview').run()
        self.assertTrue(self.button(app, '确认提交').disabled)
        self.button(app, '预览记录').click().run()
        with patch.object(duckdb_store, 'build', side_effect=RuntimeError('test import failure')):
            self.button(app, '确认提交').click().run()
        self.assert_clean(app)
        self.assertEqual(versions.current(self.cfg), self.initial)
        self.assertEqual(app.text_input(key='entry_resident_id').value, 'UI-NEW')
        self.assertEqual(app.text_area(key='entry_staff_note').value, 'changed after preview')
        self.assertTrue(any('导入 DuckDB' in e.value for e in app.error))
        self.button(app, '确认提交').click().run()
        self.assert_clean(app)
        newest = versions.current(self.cfg)
        self.assertNotEqual(newest['version'], self.initial['version'])
        _, new_db = versions.active_paths(self.cfg, newest)
        self.assertEqual(app.session_state['db_path'], str(new_db))
        self.assertEqual(app.session_state['tables']['run_metadata'].iloc[0]['input_rows'], 2)
        self.assertTrue(any('UI-NEW' in x.value for x in app.success))
        app.switch_page('pages/overview.py').run()
        self.assert_clean(app)
        self.assertEqual(app.session_state['tables']['run_metadata'].iloc[0]['input_rows'], 2)
        # No referral date was entered: the record is saved without inventing a
        # milestone, so it does not increase the strict referral funnel.
        self.assertEqual(app.session_state['tables']['funnel'].iloc[0]['n'], 1)
        self.assert_initial_untouched()

    def test_zero_and_invalid_followup_consistent_between_pages(self):
        bad = self.root / 'bad-outcomes.duckdb'
        shutil.copyfile(self.initial_db, bad)
        app = self.app(database=bad)
        self.assert_clean(app)
        self.assertEqual(next(m.value for m in app.metric if m.label == '6-Month Follow-up Coverage'), 'N/A')
        app.switch_page('pages/outcomes.py').run()
        self.assertEqual(next(m.value for m in app.metric if m.label == 'Follow-up Coverage'), 'N/A')
        with duckdb.connect(str(bad)) as con:
            con.execute('UPDATE outcomes SET known_outcome_n = -1 WHERE horizon_months = 6')
        db.read_table.clear()
        app.run()
        self.assert_clean(app)
        detail_warnings = [w.value for w in app.warning]
        self.assertTrue(any('finite, non-negative whole' in w for w in detail_warnings))
        self.assertFalse(len(app.metric))
        self.assertEqual(len(app.get('plotly_chart')), 0)
        app.switch_page('pages/overview.py').run()
        self.assert_clean(app)
        self.assertTrue(set(detail_warnings) & {w.value for w in app.warning})
        self.assertEqual(next(m.value for m in app.metric if m.label == '6-Month Follow-up Coverage'), 'N/A')

    def test_browsing_history_is_distinct_from_entry_target(self):
        versions.submit_record(self.cfg, versions.preview_record(self.cfg, self.draft()))
        app = self.app(database=self.initial_db)
        self.assert_clean(app)
        self.assertEqual(app.session_state['db_path'], str(self.initial_db))
        self.assertTrue(any('其他报告' in i.value or 'viewing another report' in i.value for i in app.info))
        self.button(app, '浏览录入数据源的当前启用报告').click().run()
        self.assert_clean(app)
        self.assertNotEqual(app.session_state['db_path'], str(self.initial_db))


if __name__ == '__main__':
    unittest.main()

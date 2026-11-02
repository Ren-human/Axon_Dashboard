"""Independent recorded-event expectations, privacy and multi-series rendering."""
import csv
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import metrics
import duckdb_store
from agent.events import monthly_activity, digest
from agent.context import authorize, fingerprint
from agent.catalog import make_spec
from agent.spec import validate
from agent.query import execute
from agent.service import execute_spec
from agent.chart_builder import build


class MonthlyActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='monthly-',dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root/'raw.csv'
        def record(rid,referral,intake,admission):
            row = {key:'' for key in metrics.REQUIRED}
            row.update(resident_id=rid,referral_date=referral,intake_date=intake,admission_date=admission,
                       current_status='phase_1',bed_capacity='4',staff_note='LOCAL ONLY: synthetic note')
            return row
        self.rows = [record('A','2024-12-20','2025-01-02','2025-02-01'),
                     record('B','2025-01-10','2025-01-11','2025-03-01'),
                     record('C','2025-02-01','','bad-date'),
                     record('D','2025-01-20','2025-02-05','2025-02-10'),
                     record('E','2026-01-01','','')]
        with self.raw.open('w',encoding='utf-8',newline='') as handle:
            writer = csv.DictWriter(handle,fieldnames=metrics.REQUIRED)
            writer.writeheader()
            writer.writerows(self.rows)
        self.meta = dict(input_sha256=digest(self.raw),as_of='2025-12-31',fiscal_year=2025)

    def database(self):
        output = self.root/'aggregates'
        result = metrics.calculate_file(self.raw,date(2026,1,15),4,'discharge',date(2025,1,1),2025)
        metrics.export_result(result,output)
        database = self.root/'report.duckdb'
        duckdb_store.build(output,database)
        cfg = self.root/'config.json'
        cfg.write_text(json.dumps(dict(source_csv=str(self.raw),version_root=str(self.root/'versions'),
                             report=dict(as_of='2026-01-15',fiscal_year=2025,capacity=4,
                                         followup_anchor='discharge',occupancy_start='2025-01-01'))),encoding='utf-8')
        environment = patch.dict(os.environ,{'HARBOURVIEW_CONFIG':str(cfg)})
        environment.start()
        self.addCleanup(environment.stop)
        return authorize('A',database,{'report':dict(tenant='A',path=str(database))})

    def test_event_dates_are_independent_of_referral_cohort(self):
        table, exclusions = monthly_activity(self.raw,self.meta)
        counts = {(month,event):n for month,event,n in table['rows']}
        self.assertEqual(counts[('2025-01','referral')],2)
        self.assertEqual(counts[('2025-01','intake')],2)  # includes A, referred in 2024
        self.assertEqual(counts[('2025-02','admission')],2)
        self.assertEqual(counts[('2025-03','admission')],1)
        self.assertEqual(counts[('2025-01','admission')],0)
        self.assertEqual(len(table['rows']),36)
        self.assertEqual(exclusions['admission']['invalid'],1)
        self.assertEqual(exclusions['intake']['missing'],2)

    def test_future_months_are_not_invented(self):
        table,_ = monthly_activity(self.raw,{**self.meta,'as_of':'2025-03-10'})
        self.assertEqual(len(table['rows']),9)
        self.assertEqual(max(row[0] for row in table['rows']),'2025-03')

    def test_raw_hash_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'does not match'):
            monthly_activity(self.raw,{**self.meta,'input_sha256':'0'*64})

    def test_duplicate_ids_are_rejected_without_exposing_id(self):
        with self.raw.open('a',encoding='utf-8',newline='') as handle:
            csv.DictWriter(handle,fieldnames=metrics.REQUIRED).writerow(self.rows[0])
        with self.assertRaisesRegex(ValueError,'unique nonempty'):
            monthly_activity(self.raw,{**self.meta,'input_sha256':digest(self.raw)})

    def test_read_only_worker_returns_only_aggregates(self):
        context = self.database()
        before = fingerprint(context.path)
        tables = execute(context,['monthly_activity'])
        self.assertEqual(list(tables['monthly_activity']),['month','event','n'])
        serialized = tables['monthly_activity'].to_json()
        self.assertNotIn('resident_id',serialized)
        self.assertNotIn('LOCAL ONLY',serialized)
        self.assertEqual(fingerprint(context.path),before)
        self.assertEqual(digest(self.raw),self.meta['input_sha256'])

    def test_new_line_chart_has_three_scatter_series(self):
        context = self.database()
        spec = make_spec('monthly_activity',filters=[dict(field='month',op='between',value=['2025-01','2025-12'])],force=True)
        reply = execute_spec(validate(spec),context)
        self.assertEqual(reply['action'],'result')
        figure = build(reply['result'])
        self.assertEqual(len(figure.data),3)
        self.assertTrue(all(trace.type=='scatter' for trace in figure.data))
        self.assertEqual(set(trace.name for trace in figure.data),{'referral','intake','admission'})
        self.assertIn('not a strict referral-cohort',reply['result']['note'])

    def test_event_filter_and_month_filter(self):
        context = self.database()
        spec = make_spec('monthly_activity','value',filters=[dict(field='event',op='eq',value='admission'),
                        dict(field='month',op='between',value=['2025-02','2025-03'])])
        reply = execute_spec(validate(spec),context)
        self.assertEqual([row['n'] for row in reply['result']['rows']],[2,1])

    def test_invalid_source_is_not_replaced_with_latest_data(self):
        context = self.database()
        with self.raw.open('a',encoding='utf-8') as handle:
            handle.write('\n')
        with self.assertRaises(ValueError):
            execute(context,['monthly_activity'])

    def test_monthly_navigation_does_not_pretend_existing_chart(self):
        context = self.database()
        reply = execute_spec(dict(schema_version='2.0',intent='navigate',metric='monthly_activity'),context)
        self.assertEqual(reply['action'],'result')

    def test_missing_dimensions_are_still_rejected(self):
        spec = make_spec('monthly_activity')
        spec['filters']=[dict(field='age',op='eq',value=25)]
        with self.assertRaises(ValueError):
            validate(spec)

    def test_existing_aggregate_queries_keep_the_six_table_contract(self):
        context = self.database()
        tables = execute(context,['funnel','occupancy','outcomes','los','quality'])
        self.assertEqual(set(tables),{'metadata','funnel','occupancy','outcomes','los','quality'})
        self.assertNotIn('monthly_activity',tables)

    def test_monthly_activity_can_be_included_in_report(self):
        context = self.database()
        reply = execute_spec(dict(schema_version='2.0',intent='report',title='Activity report',
                                  sections=['monthly_activity','funnel']),context)
        self.assertEqual(reply['report']['status'],'complete')
        self.assertIn('recorded events',reply['report']['html'])


if __name__=='__main__':
    unittest.main()

"""Offline transport regression; no real credential or network is used here."""
import io
import json
from pathlib import Path
import sys
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import gemini


class GeminiTransportTests(unittest.TestCase):
    def setUp(self):
        self.opener = MagicMock()
        self.patches = [patch('agent.gemini.urllib.request.build_opener',return_value=self.opener),
                        patch('agent.gemini.time.sleep'), patch('agent.gemini.random.uniform',return_value=0)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.request = urllib.request.Request('https://generativelanguage.googleapis.com/example',data=b'{}')

    def response(self, raw=b'{}'):
        result = MagicMock()
        result.__enter__.return_value.read.return_value = raw
        return result

    def error(self, code, headers=None):
        body = json.dumps({'error':{'status':'UNAVAILABLE','message':'sensitive-provider-prose dummy-key'}}).encode()
        return urllib.error.HTTPError('https://example.com',code,'failed',headers or {},io.BytesIO(body))

    def test_transient_503_retries_and_recovers(self):
        self.opener.open.side_effect = [self.error(503),self.response(b'{"ok":true}')]
        self.assertEqual(gemini.request_json(self.request,'test-model'),b'{"ok":true}')
        self.assertEqual(self.opener.open.call_count,2)

    def test_client_400_does_not_retry(self):
        self.opener.open.side_effect = self.error(400)
        with self.assertRaises(gemini.GeminiRequestError) as caught:
            gemini.request_json(self.request,'test-model')
        self.assertEqual(caught.exception.http_status,400)
        self.assertEqual(self.opener.open.call_count,1)

    def test_quota_without_retry_advice_does_not_retry(self):
        self.opener.open.side_effect = self.error(429)
        with self.assertRaises(gemini.GeminiRequestError):
            gemini.request_json(self.request,'test-model')
        self.assertEqual(self.opener.open.call_count,1)

    def test_short_rate_limit_advice_is_bounded(self):
        self.opener.open.side_effect = [self.error(429,{'Retry-After':'1'}),self.response()]
        gemini.request_json(self.request,'test-model')
        self.assertEqual(self.opener.open.call_count,2)

    def test_timeout_can_recover(self):
        self.opener.open.side_effect = [TimeoutError('no response'),self.response()]
        gemini.request_json(self.request,'test-model')
        self.assertEqual(self.opener.open.call_count,2)

    def test_retry_limit_has_safe_specific_error(self):
        self.opener.open.side_effect = [self.error(503),self.error(503),self.error(503)]
        with self.assertRaises(gemini.GeminiRequestError) as caught:
            gemini.request_json(self.request,'test-model')
        self.assertEqual(self.opener.open.call_count,3)
        self.assertEqual(caught.exception.attempts,3)
        self.assertIn('HTTP 503 UNAVAILABLE',str(caught.exception))
        self.assertNotIn('sensitive-provider-prose',str(caught.exception))
        self.assertNotIn('dummy-key',str(caught.exception))

    def test_invalid_provider_enum_is_not_displayed(self):
        body = io.BytesIO(b'{"error":{"status":"contains secret prose"}}')
        error = urllib.error.HTTPError('https://example.com',500,'failed',{},body)
        self.assertIsNone(gemini.provider_status(error))

    def test_response_size_limit(self):
        self.opener.open.return_value = self.response(b'x'*(gemini.MAX_RESPONSE_BYTES+1))
        with self.assertRaisesRegex(ValueError,'size limit'):
            gemini.request_json(self.request,'test-model')

    def plan_response(self,spec):
        text = json.dumps(dict(action='spec',message='',spec=spec))
        return json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':text}]}}]}).encode()

    def test_invalid_semantic_plan_gets_one_correction(self):
        from agent.catalog import make_spec
        bad = make_spec('outcomes','chart','coverage',filters=[dict(field='horizon_months',op='eq',value=6)])
        bad['output']['chart_type'] = 'line'
        good = make_spec('outcomes','value','coverage',filters=[dict(field='horizon_months',op='eq',value=6)])
        with patch('agent.gemini.settings',return_value=('dummy-key',gemini.DEFAULT_MODEL)), \
             patch('agent.gemini.request_json',side_effect=[self.plan_response(bad),self.plan_response(good)]) as call:
            result = gemini.parse_with_gemini('6 month follow-up coverage')
        self.assertEqual(result['spec'],good)
        self.assertEqual(call.call_count,2)

    def test_repeated_invalid_plan_is_withheld(self):
        with patch('agent.gemini.settings',return_value=('dummy-key',gemini.DEFAULT_MODEL)), \
             patch('agent.gemini.request_json',return_value=self.plan_response({'sql':'untrusted'})) as call:
            with self.assertRaisesRegex(ValueError,'after one correction'):
                gemini.parse_with_gemini('show occupancy')
        self.assertEqual(call.call_count,2)

    def test_provider_schema_binds_charts_to_metrics(self):
        branches = gemini.model_schema()['properties']['spec']['anyOf']
        outcomes = next(b for b in branches if b.get('properties',{}).get('metric',{}).get('enum')==['outcomes']
                        and 'view' in b.get('properties',{}))
        self.assertNotIn('line',outcomes['properties']['output']['properties']['chart_type']['enum'])

    def test_missing_key_is_not_a_rule_fallback(self):
        with patch('agent.gemini.settings',return_value=('',gemini.DEFAULT_MODEL)), \
             patch('agent.gemini.request_json') as call:
            with self.assertRaisesRegex(ValueError,'not configured'):
                gemini.parse_with_gemini('show occupancy')
        call.assert_not_called()


if __name__ == '__main__':
    unittest.main()

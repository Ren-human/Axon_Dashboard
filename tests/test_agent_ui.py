"""Real Streamlit interaction checks using only the existing synthetic fixture."""
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_refactor as base


class AnalystUI(base.Fixture):
    def setUp(self):
        super().setUp()
        from streamlit.runtime.pages_manager import PagesManager
        original = PagesManager.__init__
        def initialize(manager, *args, **kwargs):
            original(manager, *args, **kwargs)
            PagesManager.uses_pages_directory = False
        manager_patch = patch.object(PagesManager, '__init__', initialize)
        manager_patch.start()
        self.addCleanup(manager_patch.stop)
        mode_patch = patch.dict('os.environ', HARBOURVIEW_AGENT_MODE='rules')
        mode_patch.start()
        self.addCleanup(mode_patch.stop)

    def clean(self, app):
        self.assertEqual(len(app.exception),0,[x.message for x in app.exception])

    def test_chat_clarification_and_scalar(self):
        app = self.app()
        self.clean(app)
        app.chat_input[0].set_value('复发率是多少？').run()
        self.clean(app)
        self.assertEqual(app.session_state['agent_history'][-1]['reply']['action'],'clarify')
        app.chat_input[0].set_value('6月，全部到期居民').run()
        self.clean(app)
        reply = app.session_state['agent_history'][-1]['reply']
        self.assertEqual(reply['action'],'result')
        self.assertIsNone(reply['result']['rows'][0]['value'])

    def test_guidance_and_custom_chart_and_download(self):
        app = self.app()
        app.chat_input[0].set_value('查看入住率图').run()
        self.clean(app)
        self.assertEqual(app.session_state['agent_history'][-1]['reply']['action'],'guided')
        app.chat_input[0].set_value('把6月和12月随访覆盖率画在同一张图').run()
        self.clean(app)
        self.assertEqual(app.session_state['agent_history'][-1]['reply']['action'],'result')
        app.chat_input[0].set_value('生成入住率与随访专题报告').run()
        self.clean(app)
        self.assertEqual(app.session_state['agent_history'][-1]['reply']['report']['status'],'complete')
        self.assertTrue(any('HTML' in b.label for b in app.get('download_button')))

    def test_report_change_clears_pending(self):
        app = self.app()
        app.chat_input[0].set_value('复发率是多少？').run()
        self.assertIsNotNone(app.session_state['agent_pending'])
        # A new authorized report identity clears pending clarification.
        app.session_state['agent_identity'] = ('other','other','other')
        app.run()
        self.clean(app)
        self.assertIsNone(app.session_state['agent_pending'])

    def test_invalid_manual_spec_is_visible_error(self):
        app = self.app()
        app.text_area(key='agent_spec_editor').set_value('{"sql":"DROP TABLE outcomes"}').run()
        app.button(key='agent_run_spec').click().run()
        self.clean(app)
        self.assertEqual(app.session_state['agent_history'][-1]['reply']['action'],'error')

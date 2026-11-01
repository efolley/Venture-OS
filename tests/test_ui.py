"""Local Streamlit UI and subprocess boundary tests."""
import json
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from UI.service import research
from ventureos.research import fixture_run


class ServiceTests(unittest.TestCase):
    def test_demo_and_safe_arguments(self):
        with patch('UI.service.subprocess.run', return_value=SimpleNamespace(returncode=0,stdout=json.dumps(fixture_run()))) as run:
            report=research('ignored','ignored',demo=True)
            self.assertEqual(report['mode'],'fixture')
            self.assertIn('--fixture',run.call_args.args[0])
            self.assertNotIn('shell',run.call_args.kwargs)

    def test_failure_does_not_leak_provider_error(self):
        with patch('UI.service.subprocess.run',return_value=SimpleNamespace(returncode=1,stderr='secret',stdout='')):
            with self.assertRaises(ValueError) as error:
                research('','',demo=True)
            self.assertNotIn('secret',str(error.exception))

    def test_missing_configuration(self):
        with patch.dict('os.environ',{},clear=True), patch('UI.service.load_local_env'):
            with self.assertRaisesRegex(ValueError,'TAVILY_API_KEY'):
                research('Example','example.com')


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'install UI extra for interaction tests')
class StreamlitTests(unittest.TestCase):
    def test_form_validation_and_synthetic_summary(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'UI/app.py')).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value,'Venture OS')
        app.button(key='research_submit').click().run()
        self.assertIn('Enter both',app.error[0].value)
        app.toggle[0].set_value(True).run()
        app.button(key='research_submit').click().run(timeout=20)
        self.assertFalse(app.exception)
        self.assertTrue(app.warning)
        self.assertIn('company_summary',app.session_state['report']['artifact']['content'])

    def test_live_submission_summary_and_input_changes_do_not_rerun(self):
        from streamlit.testing.v1 import AppTest
        report=fixture_run(); report['mode']='live'
        with patch('UI.service.research',return_value=report) as run:
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'UI/app.py')).run()
            app.text_input[0].set_value('Example')
            app.text_input[1].set_value('https://example.com')
            app.button(key='research_submit').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(run.call_count,1)
            self.assertTrue(callable(run.call_args.kwargs['on_progress']))
            app.text_input[0].set_value('Other').run()
            self.assertEqual(run.call_count,1)


class ResearchErrorTests(unittest.TestCase):
    def test_http_upgraded_to_https(self):
        env={'MODEL_PROVIDER':'ollama','OLLAMA_MODEL':'qwen3:8b','TAVILY_API_KEY':'test','VENTUREOS_DATABASE_URL':'test'}
        with patch.dict('os.environ',env), patch('UI.service.load_local_env'), patch('UI.service.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(fixture_run()))) as run:
            research('Palantir','http://palantir.com/')
            self.assertIn('https://palantir.com/',run.call_args.args[0])

    def test_missing_model_error_is_actionable(self):
        with patch('UI.service.subprocess.run',return_value=SimpleNamespace(returncode=2,stderr='Ollama model is not installed',stdout='')):
            with self.assertRaisesRegex(ValueError,'Wait for'):
                research('','',demo=True)


class ProgressTests(unittest.TestCase):
    def test_phase_channel_and_unknown_phase(self):
        import tempfile
        from ventureos.progress import report_phase
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'phase'
            with patch.dict('os.environ',{'VENTUREOS_PROGRESS_FILE':str(path)}):
                report_phase('scraping')
                self.assertEqual(path.read_text(),'scraping')
                with self.assertRaises(ValueError):
                    report_phase('secret payload')

    def test_worker_phase_reaches_main_thread(self):
        import threading, time
        main_thread=threading.get_ident()
        labels=[]
        def worker(command, **kwargs):
            Path(kwargs['env']['VENTUREOS_PROGRESS_FILE']).write_text('scraping')
            time.sleep(0.3)
            Path(kwargs['env']['VENTUREOS_PROGRESS_FILE']).write_text('processing')
            time.sleep(0.3)
            return SimpleNamespace(returncode=0,stdout=json.dumps(fixture_run()))
        def callback(label):
            self.assertEqual(threading.get_ident(),main_thread)
            labels.append(label)
        with patch('UI.service.subprocess.run',side_effect=worker):
            research('','',demo=True,on_progress=callback)
        self.assertIn('Scraping source pages',labels)
        self.assertIn('Processing scraped results',labels)


class SpecificFailureTests(unittest.TestCase):
    def test_structured_error_reaches_ui(self):
        payload={'error':{'stage':'processing','function':'ventureos.web_live.OllamaModel.__call__',
                          'exception':'ValueError','message':'Model response was incomplete.'}}
        with patch('UI.service.subprocess.run',return_value=SimpleNamespace(returncode=1,stderr='',stdout=json.dumps(payload))):
            with self.assertRaisesRegex(ValueError,'processing.*OllamaModel.__call__'):
                research('','',demo=True)


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'install UI extra')
class HistoryPageTests(unittest.TestCase):
    def test_saved_report_navigation(self):
        from streamlit.testing.v1 import AppTest
        report=fixture_run();report.update(saved_at='2026-11-01T12:00:00-05:00',run_id='history-run',mode='live')
        with patch('UI.service.saved_reports',return_value=[report]), patch('UI.service.research') as run:
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'UI/app.py')).run()
            app.sidebar.button(key='nav_data').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.selectbox),1)
            self.assertEqual(app.selectbox[0].label,'Select a saved database report')
            self.assertIsNone(app.selectbox[0].value)
            self.assertFalse(any(item.value == 'Company summary' for item in app.subheader))
            app.selectbox[0].select(0).run()
            self.assertTrue(any(item.value == 'Company summary' for item in app.subheader))
            self.assertFalse(app.sidebar.radio)
            self.assertEqual(app.sidebar.button(key='nav_data').label,'Data Management')
            run.assert_not_called()

    def test_empty_history(self):
        from streamlit.testing.v1 import AppTest
        with patch('UI.service.saved_reports',return_value=[]):
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'UI/app.py')).run()
            app.sidebar.button(key='nav_data').click().run()
            self.assertFalse(app.exception)
            self.assertIn('No saved reports',app.info[0].value)


class HistoryLabelTests(unittest.TestCase):
    def test_dates_and_oldest_first_iteration_numbers(self):
        from UI.service import history_labels
        def report(company,date):
            return {'saved_at':date,'artifact':{'content':{'company':company}}}
        reports=[report('Basecamp','2026-11-01T15:00:00-05:00'),
                 report('Basecamp','2026-11-01T12:00:00-05:00'),
                 report('Acme','2026-11-02T12:00:00-05:00')]
        self.assertEqual(history_labels(reports),['Basecamp | Nov 1, (2)','Basecamp | Nov 1, (1)','Acme | Nov 2'])

    def test_new_york_date_boundary(self):
        from UI.service import history_labels
        self.assertEqual(history_labels([{'saved_at':'2026-11-02T02:00:00+00:00',
                          'artifact':{'content':{'company':'Basecamp'}}}]),['Basecamp | Nov 1'])

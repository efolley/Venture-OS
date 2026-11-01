"""Function logging, secrecy, rotation, and generator semantics."""
import contextlib
import io
import logging
from pathlib import Path
import tempfile
import unittest
from ventureos.logging_utils import configure_logging, logged


class LoggingTests(unittest.TestCase):
    def test_console_file_and_no_payloads(self):
        logger=logging.getLogger('ventureos.functions')
        old=logger.handlers[:]
        logger.handlers=[]
        stream=io.StringIO()
        try:
            with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stderr(stream):
                configure_logging(folder)
                configure_logging(folder)
                self.assertEqual(len(logger.handlers),2)
                @logged
                def succeed(secret):
                    return secret
                @logged
                def fail(secret):
                    raise ValueError(secret)
                self.assertEqual(succeed('secret-key-value'),'secret-key-value')
                with self.assertRaises(ValueError): fail('sensitive-document-content')
                for handler in logger.handlers: handler.flush()
                text=next(Path(folder).glob('*.log')).read_text()
                self.assertIn('event=started',text)
                self.assertIn('event=completed',text)
                self.assertIn('exception=ValueError',text)
                self.assertIn('event=failed',stream.getvalue())
                self.assertNotIn('secret-key-value',text+stream.getvalue())
                self.assertNotIn('sensitive-document-content',text+stream.getvalue())
                self.assertEqual(len(list(Path(folder).glob('*.log'))),1)
        finally:
            for handler in logger.handlers: handler.close()
            logger.handlers=old

    def test_contextmanager_behavior_preserved(self):
        events=[]
        @contextlib.contextmanager
        @logged
        def scope():
            events.append('entered')
            try:
                yield 'value'
            finally:
                events.append('exited')
        with scope() as result:
            self.assertEqual(result,'value')
        self.assertEqual(events,['entered','exited'])


class DailyLogTests(unittest.TestCase):
    def test_midnight_uses_new_york_date(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from ventureos.logging_utils import DailyFileHandler
        with tempfile.TemporaryDirectory() as folder:
            handler=DailyFileHandler(folder)
            for day, hour, minute in [(1,23,59),(2,0,1)]:
                record=logging.LogRecord('test',logging.INFO,'',0,'entry',(),None)
                record.created=datetime(2026,11,day,hour,minute,tzinfo=ZoneInfo('America/New_York')).timestamp()
                handler.emit(record)
            self.assertEqual(sorted(p.name for p in Path(folder).glob('*.log')),
                             ['2026-11-01.log','2026-11-02.log'])

    def test_processes_append_to_same_file(self):
        import subprocess, sys
        script="from ventureos.logging_utils import configure_logging; import sys; log=configure_logging(sys.argv[1]); [log.info('entry=%s', i) for i in range(30)]"
        with tempfile.TemporaryDirectory() as folder:
            processes=[subprocess.Popen([sys.executable,'-c',script,folder],stderr=subprocess.DEVNULL) for _ in range(3)]
            for process in processes:
                self.assertEqual(process.wait(timeout=15),0)
            files=list(Path(folder).glob('*.log'))
            self.assertEqual(len(files),1)
            self.assertEqual(len(files[0].read_text().splitlines()),90)

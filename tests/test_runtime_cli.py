import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

class RuntimeCliTests(unittest.TestCase):
    def test_preview_without_site_packages(self):
        result=subprocess.run([sys.executable,'-S','-m','ventureos','--brief','examples/agency-brief.json'],capture_output=True,text=True,check=True,env={**os.environ,'PYTHONPATH':str(Path('src').resolve())})
        self.assertEqual(json.loads(result.stdout)['mode'],'preview')

    def test_missing_runtime_configuration_fails_cleanly(self):
        env={k:v for k,v in os.environ.items() if k!='VENTUREOS_DATABASE_URL'}
        result=subprocess.run([sys.executable,'-m','ventureos','--brief','examples/agency-brief.json','--execute-demo','--tenant','test','--run-id','demo'],env=env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('VENTUREOS_DATABASE_URL',result.stderr)

    @unittest.skipUnless(os.environ.get('VENTUREOS_TEST_DSN'),'requires disposable PostgreSQL database')
    def test_opt_in_demo_is_persistent_and_repeatable(self):
        env={**os.environ,'VENTUREOS_DATABASE_URL':os.environ['VENTUREOS_TEST_DSN']}
        command=[sys.executable,'-m','ventureos','--brief','examples/agency-brief.json','--execute-demo','--tenant',str(uuid.uuid4()),'--run-id','demo']
        first=json.loads(subprocess.run(command,env=env,capture_output=True,text=True,check=True).stdout)
        second=json.loads(subprocess.run(command,env=env,capture_output=True,text=True,check=True).stdout)
        self.assertEqual(first['status'],'succeeded')
        self.assertEqual(first['artifact'],second['artifact'])
        self.assertEqual(second['attempts'],1)

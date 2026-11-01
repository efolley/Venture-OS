"""Local .env parsing without credentials or process-setting overrides."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ventureos.config import load_local_env


class ConfigTests(unittest.TestCase):
    def test_load_quotes_preserve_environment_and_literal_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'.env'
            path.write_text('KEY="local value"\nEXISTING=file\nLITERAL=${KEY}\n')
            with patch.dict(os.environ,{'EXISTING':'process'},clear=True):
                load_local_env(path)
                self.assertEqual(os.environ['KEY'],'local value')
                self.assertEqual(os.environ['EXISTING'],'process')
                self.assertEqual(os.environ['LITERAL'],'${KEY}')

    def test_missing_file_is_optional(self):
        with tempfile.TemporaryDirectory() as folder:
            load_local_env(Path(folder)/'absent')

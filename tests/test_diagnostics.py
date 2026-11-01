import unittest
from ventureos.diagnostics import describe_failure, phase
from ventureos.web_intelligence import public_url


class DiagnosticTests(unittest.TestCase):
    def test_function_and_no_sensitive_message(self):
        token=phase.set('scraping')
        try:
            try:
                public_url('secret-api-value')
            except ValueError as error:
                detail=describe_failure(error)
            self.assertEqual(detail['stage'],'scraping')
            self.assertEqual(detail['function'],'ventureos.web_intelligence.public_url')
            self.assertNotIn('secret-api-value',str(detail))
        finally:
            phase.reset(token)

    def test_known_failure_and_unknown_secret(self):
        self.assertIn('No source pages',describe_failure(ValueError('no usable research evidence'))['message'])
        self.assertNotIn('password',str(describe_failure(ValueError('password=secret'))))

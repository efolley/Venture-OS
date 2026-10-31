import json
import subprocess
import sys
import unittest
from ventureos.contracts import BusinessBrief
from ventureos.harness import AgentHarness
from ventureos.agents import AGENTS

class PreviewTests(unittest.TestCase):
    def test_preview_contract(self):
        plan = AgentHarness().plan(BusinessBrief('goal', 'market', 'service', []))
        seen = set()
        for step in plan.steps:
            self.assertTrue(set(step.depends_on) <= seen)
            seen.add(step.id)
        self.assertTrue({a.id for a in AGENTS} <= {s.owner for s in plan.steps})
        self.assertEqual(plan.mode, 'preview')

    def test_cli_without_credentials(self):
        result = subprocess.run([sys.executable, '-m', 'ventureos', '--brief', 'examples/agency-brief.json'], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['mode'], 'preview')

    def test_invalid_brief(self):
        with self.assertRaises(ValueError):
            BusinessBrief('', 'market', 'service', [])

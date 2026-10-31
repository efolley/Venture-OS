import unittest
from ventureos.execution import Artifact, Task, AgentContext, Agent

class EnvelopeTests(unittest.TestCase):
    def test_roundtrip_and_identity(self):
        task = Task('tenant', 'run', 'task', 'research', {'company': 'Acme'})
        self.assertEqual(Task.from_dict(task.to_dict()), task)
        artifact = Artifact('tenant', 'run', 'task', 'brief', {'finding': 'test'}, sources=('https://example.com',))
        self.assertEqual(Artifact.from_dict(artifact.to_dict()), artifact)
        self.assertEqual(AgentContext(task, {}).task.tenant_id, 'tenant')

    def test_invalid_envelopes(self):
        for args in [('', 'run', 'task', 'research', {}), ('tenant', 'run', 'task', 'research', {'bad': object()})]:
            with self.assertRaises(ValueError):
                Task(*args)
        with self.assertRaises(ValueError):
            Task('t', 'r', 'x', 'a', {}, max_attempts=0)

    def test_protocol(self):
        class Example:
            def execute(self, context):
                t = context.task
                return Artifact(t.tenant_id, t.run_id, t.task_id, 'brief', {})
        self.assertIsInstance(Example(), Agent)

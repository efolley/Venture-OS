import unittest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from ventureos.telemetry import operation

class TelemetryTests(unittest.TestCase):
    def test_span_export_without_exception_payload(self):
        exporter=InMemorySpanExporter(); provider=TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer=provider.get_tracer('test')
        with self.assertRaises(RuntimeError):
            with operation('task.execute',{'task.id':'123'},tracer=tracer):
                raise RuntimeError('secret@example.com')
        spans=exporter.get_finished_spans()
        self.assertEqual(len(spans),1)
        self.assertEqual(spans[0].attributes['task.id'],'123')
        self.assertEqual(spans[0].status.status_code.name,'ERROR')
        self.assertEqual(len(spans[0].events),0)
        self.assertNotIn('secret',str(spans[0].status.description))

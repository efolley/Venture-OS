"""Optional OpenTelemetry API instrumentation; the host configures exporters."""
from ventureos.logging_utils import logged
from contextlib import contextmanager


@contextmanager
@logged
def operation(name: str, attributes: dict, *, tracer=None):
    if tracer is None:
        try:
            from opentelemetry import trace
            tracer=trace.get_tracer('ventureos')
        except ImportError:
            yield
            return
    # Do not export raw exception messages, prompts, documents, or tool arguments.
    with tracer.start_as_current_span(name,attributes=attributes,record_exception=False,set_status_on_exception=False) as span:
        try:
            yield span
        except Exception:
            from opentelemetry.trace import Status,StatusCode
            span.set_status(Status(StatusCode.ERROR))
            raise

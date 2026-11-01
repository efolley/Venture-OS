"""Safe structured failures without raw exception messages or data."""
from ventureos.logging_utils import logged
from contextvars import ContextVar
import re

phase = ContextVar('research_phase', default='checking')


@logged
def describe_failure(error):
    origin = 'ventureos.research.main'
    trace = error.__traceback__
    while trace:
        frame = trace.tb_frame
        module = frame.f_globals.get('__name__','')
        if module.startswith('ventureos.') and module not in ('ventureos.logging_utils','ventureos.telemetry'):
            origin = module + '.' + frame.f_code.co_qualname
        trace = trace.tb_next
    reasons = {
        'no usable research evidence':'No source pages could be fetched successfully.',
        'invalid research or unsupported citation':'Model output failed research schema or citation validation.',
        'artifact failed runtime validation':'Research artifact failed runtime validation.',
        'Ollama did not finish its response':'Ollama stopped before completing valid JSON; the output limit may have been reached.',
        'Ollama model is not installed':'The selected Ollama model is not installed yet.',
        'Ollama server is unavailable':'Cannot connect to the local Ollama server.',
        'budget exceeded':'The task exhausted its configured budget.',
        'deadline exceeded':'The task exceeded its configured deadline.',
        'nonpublic DNS destination denied':'The source resolved to a blocked private network address.',
        'content policy blocked instruction pattern':'Source or model content triggered the injection check.',
        'only HTTPS on port 443 is supported':'The source URL must use HTTPS on port 443.',
        'response size limit exceeded':'The source exceeded the response size limit.',
    }
    message = reasons.get(str(error))
    if message is None and re.fullmatch(r'HTTP request failed with status \d{3}',str(error)):
        message = str(error) + '.'
    if message is None:
        if isinstance(error,TimeoutError):
            message='An operation timed out.'
        elif type(error).__name__ == 'JSONDecodeError':
            message='The provider returned malformed JSON.'
        elif 'psycopg' in type(error).__module__:
            message='A PostgreSQL operation failed; check database availability and permissions.'
        else:
            message='Operation failed; inspect the named function and local logs.'
    return {'stage':phase.get(), 'function':origin, 'exception':type(error).__name__, 'message':message}

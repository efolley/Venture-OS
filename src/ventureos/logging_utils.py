"""Payload-free function logs shared by local calendar day across processes."""
from functools import wraps
import inspect
import logging
from datetime import datetime
import fcntl
from zoneinfo import ZoneInfo
import os
from pathlib import Path
import sys
import threading
import time

_lock = threading.Lock()


LOG_TIMEZONE = ZoneInfo('America/New_York')


class LocalFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        stamp = datetime.fromtimestamp(record.created, LOG_TIMEZONE)
        return stamp.isoformat(timespec='milliseconds')


class DailyFileHandler(logging.Handler):
    """Append complete records under a cross-process lock; never split a day."""
    def __init__(self, folder):
        super().__init__()
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def emit(self, record):
        try:
            day = datetime.fromtimestamp(record.created, LOG_TIMEZONE).strftime('%Y-%m-%d')
            path = self.folder / (day + '.log')
            message = (self.format(record) + '\n').encode('utf-8')
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(descriptor, 'ab') as output:
                fcntl.flock(output.fileno(), fcntl.LOCK_EX)
                try:
                    output.write(message)
                    output.flush()
                finally:
                    fcntl.flock(output.fileno(), fcntl.LOCK_UN)
        except OSError:
            # Never print a potentially sensitive LogRecord in an error report.
            print('VENTUREOS file_logging_unavailable', file=sys.stderr)


def configure_logging(directory=None):
    logger = logging.getLogger('ventureos.functions')
    with _lock:
        if logger.handlers:
            return logger
        logger.setLevel(logging.INFO)
        logger.propagate = False
        formatter = LocalFormatter('VENTUREOS %(asctime)s %(levelname)s pid=%(process)d thread=%(threadName)s %(message)s')
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        logger.addHandler(console)
        folder = Path(directory) if directory else Path(__file__).resolve().parents[2] / 'logs'
        try:
            handler = DailyFileHandler(folder)
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        except OSError:
            logger.warning('file_logging_unavailable')
    return logger


def logged(function):
    """Log names, durations, and exception types only, never args or results."""
    name = function.__module__ + '.' + function.__qualname__

    def start():
        logger = configure_logging()
        logger.info('function=%s event=started', name)
        return logger, time.monotonic()

    def finish(logger, started):
        logger.info('function=%s event=completed duration_ms=%.2f', name, (time.monotonic()-started)*1000)

    def failed(logger, started, error):
        logger.error('function=%s event=failed duration_ms=%.2f exception=%s',
                     name, (time.monotonic()-started)*1000, type(error).__name__)

    if inspect.isgeneratorfunction(function):
        @wraps(function)
        def generator(*args, **kwargs):
            logger, started = start()
            try:
                result = yield from function(*args, **kwargs)
            except BaseException as error:
                failed(logger, started, error)
                raise
            finish(logger, started)
            return result
        return generator

    @wraps(function)
    def wrapper(*args, **kwargs):
        logger, started = start()
        try:
            result = function(*args, **kwargs)
        except BaseException as error:
            failed(logger, started, error)
            raise
        finish(logger, started)
        return result
    return wrapper

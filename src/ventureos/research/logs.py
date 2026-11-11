"""Logging for the Research agent: a decorator for function calls and a one-call setup.

Logs record function names, durations, counts, and error types. They never record
API keys, prompts, page text, or model output.

`@logged` marks pipeline steps (INFO). `@logged_debug` marks small helpers (DEBUG),
so the default log stays readable. Set VENTUREOS_LOG_LEVEL=DEBUG to see every call.
"""

import functools
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("ventureos.research")
logger.addHandler(logging.NullHandler())  # silent until setup_logging() is called

_MAX_ERROR_CHARS = 300


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def logged(function: Callable[..., Any] | None = None, *, level: int = logging.INFO) -> Any:
    """Log start, completion with duration, and failure of a function call."""

    def decorate(target: Callable[..., Any]) -> Callable[..., Any]:
        name = f"{target.__module__.removeprefix('ventureos.')}.{target.__qualname__}"
        failure_level = logging.WARNING if level >= logging.INFO else level

        @functools.wraps(target)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger.log(level, "%s started", name)
            started = time.perf_counter()
            try:
                result = target(*args, **kwargs)
            except Exception as error:
                logger.log(
                    failure_level,
                    "%s failed duration_ms=%.1f error=%s: %s",
                    name, _elapsed_ms(started), type(error).__name__,
                    str(error)[:_MAX_ERROR_CHARS],
                )
                raise
            logger.log(level, "%s completed duration_ms=%.1f", name, _elapsed_ms(started))
            return result

        return wrapper

    return decorate(function) if function is not None else decorate


logged_debug = functools.partial(logged, level=logging.DEBUG)


def log_progress(module: str, input_data: object, output_data: object, status: str) -> None:
    """Progress callback that logs the step name and status only, never the payloads."""
    del input_data, output_data
    logger.info("progress module=%s status=%s", module, status)


def setup_logging(level: str | None = None, log_dir: str | Path | None = None) -> logging.Logger:
    """Send research logs to the terminal and logs/research.log. Safe to call repeatedly."""
    chosen = (level or os.getenv("VENTUREOS_LOG_LEVEL", "INFO")).upper()
    logger.setLevel(getattr(logging, chosen, logging.INFO))
    if any(getattr(handler, "_ventureos", False) for handler in logger.handlers):
        return logger
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    directory = Path(log_dir or os.getenv("VENTUREOS_LOG_DIR", "logs"))
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(
            directory / "research.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        ))
    except OSError as error:
        logger.warning("file logging disabled: %s", error)
    for handler in handlers:
        handler.setFormatter(formatter)
        handler._ventureos = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.propagate = False
    return logger

"""Logging setup: one stdlib ``LOGGING`` config for everything, loguru included.

Django calls :func:`configure` (``settings.LOGGING_CONFIG``) with ``settings.LOGGING`` during
``django.setup()``, which runs for gunicorn, management commands, tests and Celery workers.

Some modules log through loguru (``from loguru import logger``). Instead of running two logging
systems side by side, loguru is routed *into* the standard ``logging`` module: its default stderr
sink is removed and every loguru record is re-emitted on the stdlib logger named after the module
that produced it (e.g. ``shop.views.payment``). Levels, formatting and handlers are therefore all
controlled by ``settings.LOGGING`` (and the ``LOG_LEVEL`` env var).
"""

import logging
import logging.config

from loguru import logger as loguru_logger


def forward_loguru_message(message):
    """Loguru sink: re-emit a loguru record on the stdlib logger named after its module.

    The stdlib record carries ``exc_info`` (not loguru's pre-rendered traceback), so tracebacks are
    formatted by ``logging`` like every other log line, and loguru's ``diagnose`` mode, which prints
    local variable values and could leak secrets, is never used.
    """
    loguru_record = message.record
    level = loguru_record['level'].no
    target = logging.getLogger(loguru_record['name'] or '')
    if not target.isEnabledFor(level):
        return
    exc = loguru_record['exception']
    record = target.makeRecord(
        target.name,
        level,
        loguru_record['file'].path,
        loguru_record['line'],
        loguru_record['message'],
        (),
        (exc.type, exc.value, exc.traceback) if exc else None,
        loguru_record['function'],
    )
    record.levelname = loguru_record['level'].name  # keeps loguru-only levels such as SUCCESS readable
    target.handle(record)


def route_loguru_to_logging():
    """Replace loguru's sinks (incl. its default stderr sink) with the stdlib forwarder. Idempotent."""
    loguru_logger.remove()
    loguru_logger.add(forward_loguru_message, level=0, format='{message}', backtrace=False, diagnose=False)


def configure(logging_settings):
    """``LOGGING_CONFIG`` callable: apply the dictConfig, then route loguru through it."""
    logging.config.dictConfig(logging_settings)
    route_loguru_to_logging()

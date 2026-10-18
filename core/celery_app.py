import os

from celery import Celery
from celery.signals import setup_logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("core")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()


@setup_logging.connect
def use_django_logging(**kwargs):
    """Leave logging to Django's LOGGING (core/settings.py) in workers and beat.

    Having a receiver for this signal stops Celery from adding its own root handler (which would
    duplicate every line); django.setup() has already applied LOGGING, so ``LOG_LEVEL`` controls
    worker output and the ``--loglevel`` CLI flag has no effect.
    """

from celery import Celery
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "a_core.settings")

app = Celery("a_core")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()
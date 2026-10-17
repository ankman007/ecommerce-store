"""Settings for running the test suite: SQLite, eager Celery, no real email or Stripe."""

import os

os.environ.setdefault('SECRET_KEY', 'test-secret-key')
# Keep test output clean; run with LOG_LEVEL=DEBUG to see application logs while debugging a test.
os.environ.setdefault('LOG_LEVEL', 'CRITICAL')

from .settings import *  # noqa: E402,F401,F403

SECRET_KEY = 'test-secret-key'
DEBUG = False
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# In-memory mailer; the test runner also forces every MAILERS alias to locmem so mail.outbox works.
MAILERS = {'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

STRIPE_SECRET_KEY = 'sk_test_dummy'
STRIPE_PUBLIC_KEY = 'pk_test_dummy'

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

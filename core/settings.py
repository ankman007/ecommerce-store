"""Django settings for the store.

Every value that differs between environments comes from an environment variable (a ``.env``
file in the project root is loaded for local development). Sections:

  1. Helpers / core           5. Static & media files       9. Celery
  2. Apps & middleware        6. Authentication (allauth)  10. Stripe
  3. Templates & URLs         7. Email (MAILERS)           11. Security hardening
  4. Database & i18n          8. Logging                   12. Request limits
"""

import logging
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(os.path.join(BASE_DIR, '.env'))


# ---------------------------------------------------------------------------
# 1. Helpers / core
# ---------------------------------------------------------------------------


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None or value.strip() == '':
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name, default=''):
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


DEBUG = env_bool('DEBUG', False)

SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        # Insecure throwaway key for local development only.
        SECRET_KEY = 'django-insecure-dev-only-key-do-not-use-in-production'
    else:
        raise ImproperlyConfigured('SECRET_KEY environment variable must be set when DEBUG is off.')

ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1')

CSRF_TRUSTED_ORIGINS = env_list(
    'CSRF_TRUSTED_ORIGINS',
    'https://a1albanywholesale.com,https://www.a1albanywholesale.com',
)

SITE_ID = 1

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# 2. Apps & middleware
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_cleanup.apps.CleanupConfig',
    'django_htmx',
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'users',
    'shop',
]

INSTALLED_APPS += ['ckeditor']

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
]


# ---------------------------------------------------------------------------
# 3. Templates & URLs
# ---------------------------------------------------------------------------

ROOT_URLCONF = 'core.urls'
WSGI_APPLICATION = 'core.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'shop.context_processors.cart_count',
                'shop.context_processors.site_context',
            ],
        },
    },
]

if DEBUG:
    # Django caches templates even in DEBUG and only refreshes them under runserver's
    # autoreloader; under gunicorn that would hide template edits until a restart.
    TEMPLATES[0]['APP_DIRS'] = False
    TEMPLATES[0]['OPTIONS']['loaders'] = [
        'django.template.loaders.filesystem.Loader',
        'django.template.loaders.app_directories.Loader',
    ]


# ---------------------------------------------------------------------------
# 4. Database & internationalisation
# ---------------------------------------------------------------------------

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        # '' (not None) when unset, so the MySQL backend falls back to localhost instead of crashing.
        'HOST': os.getenv('DB_HOST', ''),
        'PORT': os.getenv('DB_PORT', '3306'),
    }
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# 5. Static & media files (static files are served by WhiteNoise)
# ---------------------------------------------------------------------------

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# ---------------------------------------------------------------------------
# 6. Authentication (django.contrib.auth + allauth)
# ---------------------------------------------------------------------------

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_REDIRECT_URL = '/'

# Rate limits are enabled by default in allauth 65.x.
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'username*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION = os.getenv('ACCOUNT_EMAIL_VERIFICATION', 'optional')
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = False
ACCOUNT_DEFAULT_HTTP_PROTOCOL = 'http' if DEBUG else 'https'


# ---------------------------------------------------------------------------
# 7. Email
# ---------------------------------------------------------------------------
# Django 6.1 replaces the EMAIL_BACKEND/EMAIL_HOST/... settings with MAILERS. Those names must
# not be defined as settings any more (Django refuses to start when both are set), so the same
# environment variables are read into lowercase locals here and mapped onto MAILERS["default"].
#   EMAIL_BACKEND        backend class path (default: SMTP)
#   EMAIL_HOST / EMAIL_PORT / EMAIL_USE_TLS / EMAIL_TIMEOUT   SMTP connection (default Gmail, 587, TLS)
#   EMAIL_HOST_USER / EMAIL_HOST_PASSWORD                    SMTP login
#   DEFAULT_FROM_EMAIL   sender address (defaults to EMAIL_HOST_USER)
#   RECIPIENT_EMAIL      shop inbox for contact-form and order-review emails
# Code that used settings.EMAIL_HOST_USER as the sender should use settings.DEFAULT_FROM_EMAIL.

_smtp_backend = 'django.core.mail.backends.smtp.EmailBackend'
_email_backend = os.getenv('EMAIL_BACKEND') or _smtp_backend
_email_user = os.getenv('EMAIL_HOST_USER') or ''

if _email_backend == _smtp_backend:
    _email_options = {
        'host': os.getenv('EMAIL_HOST') or 'smtp.gmail.com',
        'port': int(os.getenv('EMAIL_PORT') or 587),
        'username': _email_user,
        'password': os.getenv('EMAIL_HOST_PASSWORD') or '',
        'use_tls': env_bool('EMAIL_USE_TLS', True),
        # Don't let a hung SMTP server block a gunicorn/Celery worker forever.
        'timeout': int(os.getenv('EMAIL_TIMEOUT') or 30),
    }
else:
    # console/locmem/dummy backends take no connection options.
    _email_options = {}

MAILERS = {
    'default': {
        'BACKEND': _email_backend,
        'OPTIONS': _email_options,
    },
}

DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL') or _email_user or 'webmaster@localhost'
SERVER_EMAIL = os.getenv('SERVER_EMAIL') or DEFAULT_FROM_EMAIL
RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')


# ---------------------------------------------------------------------------
# 8. Logging
# ---------------------------------------------------------------------------
# Everything goes to the console (stdout/stderr is collected by Docker/systemd). LOG_LEVEL sets the
# level for the project and Django (default INFO); noisy third-party loggers are capped at WARNING.
# loguru (used in shop views/tasks) is routed into this config by core.logging_config, so there is
# one format and one level switch for both. Never log secrets, tokens, card data or full Stripe
# payloads; log ids (order id, session id) instead.

LOG_LEVEL = (os.getenv('LOG_LEVEL') or 'INFO').upper()
_log_levels = logging.getLevelNamesMapping()
if LOG_LEVEL not in _log_levels:
    raise ImproperlyConfigured(f'LOG_LEVEL must be a logging level name such as INFO or DEBUG, got {LOG_LEVEL!r}.')


def _at_least(level):
    """``level``, or LOG_LEVEL when that is stricter (so LOG_LEVEL=ERROR also quiets chatty loggers)."""
    return max(LOG_LEVEL, level, key=_log_levels.get)


_quiet_level = _at_least('WARNING')

LOGGING_CONFIG = 'core.logging_config.configure'
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '{asctime} {levelname:<8} [{name}] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        # Replaces Django's default 'django' handlers; records propagate to the root console handler.
        'django': {'handlers': [], 'level': LOG_LEVEL, 'propagate': True},
        # 5xx responses (with traceback). 4xx "Not Found"/"Bad Request" warnings are too noisy.
        'django.request': {'level': _at_least('ERROR'), 'propagate': True},
        # DisallowedHost, suspicious operations, CSRF failures.
        'django.security': {'level': _quiet_level, 'propagate': True},
        'django.db.backends': {'level': _quiet_level, 'propagate': True},
        'django.template': {'level': _quiet_level, 'propagate': True},
        'django.utils.autoreload': {'level': _quiet_level, 'propagate': True},
        'celery': {'level': LOG_LEVEL, 'propagate': True},
        'kombu': {'level': _quiet_level, 'propagate': True},
        'amqp': {'level': _quiet_level, 'propagate': True},
        'stripe': {'level': _quiet_level, 'propagate': True},
        'urllib3': {'level': _quiet_level, 'propagate': True},
        'PIL': {'level': _quiet_level, 'propagate': True},
        'asyncio': {'level': _quiet_level, 'propagate': True},
    },
}


# ---------------------------------------------------------------------------
# 9. Celery
# ---------------------------------------------------------------------------

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND')

CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
# With namespace='CELERY' these must be the new-style names (CELERY_ + upper-cased setting name);
# the old CELERY_TRACK_STARTED / CELERY_SEND_EVENTS spellings were silently ignored.
CELERY_TASK_TRACK_STARTED = True
CELERY_WORKER_SEND_TASK_EVENTS = True  # lets Flower show task events
CELERY_TIMEZONE = 'UTC'
# Keep Django's LOGGING (above) in charge of worker output instead of Celery replacing root handlers.
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_BEAT_SCHEDULE = {
    # Cancel abandoned checkouts and catch any payment whose webhook was missed.
    'expire-stale-checkouts': {
        'task': 'shop.tasks.expire_stale_checkouts',
        'schedule': 15 * 60,
    },
}


# ---------------------------------------------------------------------------
# 10. Stripe
# ---------------------------------------------------------------------------

STRIPE_PUBLIC_KEY = os.getenv('STRIPE_PUBLIC_KEY')
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')


# ---------------------------------------------------------------------------
# 11. Security hardening (only enforced when DEBUG is off; each is env-tunable)
# ---------------------------------------------------------------------------

# Nginx terminates TLS and forwards the original scheme/host.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Off by default: Nginx already redirects HTTP->HTTPS, and enabling this without Nginx
# sending X-Forwarded-Proto would cause a redirect loop. Set SECURE_SSL_REDIRECT=True to enforce in Django too.
SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', False)
SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', not DEBUG)
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '0' if DEBUG else '3600'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', False)
SECURE_HSTS_PRELOAD = env_bool('SECURE_HSTS_PRELOAD', False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = int(os.getenv('SESSION_COOKIE_AGE', str(60 * 60 * 24 * 14)))


# ---------------------------------------------------------------------------
# 12. Request size limits (file bodies are additionally capped by Nginx client_max_body_size)
# ---------------------------------------------------------------------------

DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv('DATA_UPLOAD_MAX_MEMORY_SIZE', str(5 * 1024 * 1024)))
FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv('FILE_UPLOAD_MAX_MEMORY_SIZE', str(5 * 1024 * 1024)))
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000
DATA_UPLOAD_MAX_NUMBER_FILES = 20

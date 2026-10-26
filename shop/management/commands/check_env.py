"""Check that the production configuration is complete and safe.

Runs before migrating every time the web container starts (see docker-compose.dokploy.yml).
Problems are printed by setting name only; secret values are never echoed.
Exits non-zero when there is any error (or any warning with --fail-on-warning).
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Values copied from .env.example / .env.dokploy.example or used for local builds and tests.
PLACEHOLDER_SECRET_KEYS = {
    'your-django-secret-key',
    'replace-with-a-long-random-secret',
    'collectstatic-only',
    'test-secret-key',
    'change-me',
    'secret',
}
PLACEHOLDER_MARKERS = (
    'replace-me',
    'replace-with',
    'change-me',
    'your-django',
    'your-email',
    'your-16-character',
    'example.com',
    'example.org',
    '****',
)

SMTP_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
NON_DELIVERING_EMAIL_BACKENDS = {
    'django.core.mail.backends.console.EmailBackend',
    'django.core.mail.backends.locmem.EmailBackend',
    'django.core.mail.backends.dummy.EmailBackend',
    'django.core.mail.backends.filebased.EmailBackend',
}
LOCAL_HOSTS = {'localhost', '127.0.0.1', '[::1]', '::1', 'web'}


def _value(name):
    value = getattr(settings, name, None)
    return value.strip() if isinstance(value, str) else value


def _default_mailer():
    """Backend path and options of MAILERS['default'] (Django 6.1 replaced the EMAIL_* settings)."""
    mailer = (getattr(settings, 'MAILERS', None) or {}).get('default') or {}
    options = {
        key: value.strip() if isinstance(value, str) else value for key, value in (mailer.get('OPTIONS') or {}).items()
    }
    return (mailer.get('BACKEND') or '').strip(), options


def _looks_like_placeholder(value):
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _stripe_mode(key, prefixes):
    """Return 'live', 'test' or None for a Stripe key with one of the given prefixes."""
    for prefix in prefixes:
        for mode in ('live', 'test'):
            if key.startswith(f'{prefix}_{mode}_'):
                return mode
    return None


class Command(BaseCommand):
    # System checks run separately (manage.py check --deploy); keep this output to the env report.
    requires_system_checks = []
    help = 'Validate production settings (secrets, hosts, database, Celery, Stripe, email) without printing them.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fail-on-warning',
            action='store_true',
            help='Exit non-zero on warnings as well as errors.',
        )

    def handle(self, *args, **options):
        self.errors = []
        self.warnings = []

        self.check_django()
        self.check_database()
        self.check_celery()
        self.check_stripe()
        self.check_email()

        for message in self.errors:
            self.stdout.write(self.style.ERROR(f'ERROR    {message}'))
        for message in self.warnings:
            self.stdout.write(self.style.WARNING(f'WARNING  {message}'))

        summary = f'{len(self.errors)} error(s), {len(self.warnings)} warning(s)'
        if self.errors or (self.warnings and options['fail_on_warning']):
            raise CommandError(f'Environment check failed: {summary}.')
        self.stdout.write(self.style.SUCCESS(f'Environment check passed: {summary}.'))

    def error(self, message):
        self.errors.append(message)

    def warn(self, message):
        self.warnings.append(message)

    def check_django(self):
        secret_key = _value('SECRET_KEY') or ''
        if not secret_key:
            self.error('SECRET_KEY is not set.')
        elif (
            secret_key.startswith('django-insecure')
            or secret_key.lower() in PLACEHOLDER_SECRET_KEYS
            or _looks_like_placeholder(secret_key)
        ):
            self.error('SECRET_KEY is a development or placeholder value; generate a new random key.')
        elif len(secret_key) < 50 or len(set(secret_key)) < 5:
            self.error('SECRET_KEY is too short or simple (use at least 50 random characters).')

        if settings.DEBUG:
            self.error('DEBUG is on; set DEBUG=False.')

        hosts = [h for h in (settings.ALLOWED_HOSTS or []) if h]
        if not hosts:
            self.error('ALLOWED_HOSTS is empty.')
        elif '*' in hosts:
            self.error('ALLOWED_HOSTS contains "*"; list the real domain names.')
        elif all(h in LOCAL_HOSTS for h in hosts):
            self.error('ALLOWED_HOSTS only lists local hosts; add the public domain name(s).')

        origins = [o for o in (getattr(settings, 'CSRF_TRUSTED_ORIGINS', None) or []) if o]
        if not origins:
            self.error('CSRF_TRUSTED_ORIGINS is empty; add https://<your-domain>.')
        else:
            if any(not o.startswith('https://') for o in origins):
                self.warn('CSRF_TRUSTED_ORIGINS has entries that are not https://.')
            if any(_looks_like_placeholder(o) for o in origins):
                self.error('CSRF_TRUSTED_ORIGINS still contains placeholder domains.')
        if any(_looks_like_placeholder(h) for h in hosts):
            self.error('ALLOWED_HOSTS still contains placeholder domains.')

        if not getattr(settings, 'SESSION_COOKIE_SECURE', False):
            self.warn('SESSION_COOKIE_SECURE is off; session cookies can leak over http.')
        if not getattr(settings, 'CSRF_COOKIE_SECURE', False):
            self.warn('CSRF_COOKIE_SECURE is off.')

    def check_database(self):
        db = settings.DATABASES.get('default', {})
        engine = db.get('ENGINE', '')
        if 'sqlite' in engine:
            self.error('DATABASES["default"] uses SQLite; production runs on MySQL.')
            return
        for key, env_name in (
            ('NAME', 'DB_NAME'),
            ('USER', 'DB_USER'),
            ('PASSWORD', 'DB_PASSWORD'),
            ('HOST', 'DB_HOST'),
        ):
            if not db.get(key):
                self.error(f'Database {key} is not set ({env_name}).')
        password = db.get('PASSWORD') or ''
        if password and (_looks_like_placeholder(password) or len(password) < 12):
            self.error('Database PASSWORD (DB_PASSWORD) is a placeholder or shorter than 12 characters.')

    def check_celery(self):
        broker = _value('CELERY_BROKER_URL') or ''
        if not broker:
            self.error('CELERY_BROKER_URL is not set; background jobs (emails, checkout expiry) would not run.')
        elif not broker.startswith(('redis://', 'rediss://', 'amqp://', 'amqps://')):
            self.warn('CELERY_BROKER_URL does not look like a redis:// or amqp:// URL.')
        if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
            self.warn('CELERY_TASK_ALWAYS_EAGER is on; tasks run inside web requests.')

    def check_stripe(self):
        public_key = _value('STRIPE_PUBLIC_KEY') or ''
        secret_key = _value('STRIPE_SECRET_KEY') or ''
        webhook_secret = _value('STRIPE_WEBHOOK_SECRET') or ''

        public_mode = secret_mode = None
        if not public_key:
            self.error('STRIPE_PUBLIC_KEY is not set.')
        elif '*' in public_key or _looks_like_placeholder(public_key):
            self.error('STRIPE_PUBLIC_KEY is a placeholder.')
        else:
            public_mode = _stripe_mode(public_key, ('pk',))
            if public_mode is None:
                self.error('STRIPE_PUBLIC_KEY does not look like a publishable key (pk_live_/pk_test_).')

        if not secret_key:
            self.error('STRIPE_SECRET_KEY is not set.')
        elif '*' in secret_key or _looks_like_placeholder(secret_key):
            self.error('STRIPE_SECRET_KEY is a placeholder.')
        else:
            secret_mode = _stripe_mode(secret_key, ('sk', 'rk'))
            if secret_mode is None:
                self.error('STRIPE_SECRET_KEY does not look like a secret or restricted key (sk_/rk_).')

        if public_mode and secret_mode:
            if public_mode != secret_mode:
                self.error(f'Stripe keys are from different modes (publishable: {public_mode}, secret: {secret_mode}).')
            elif secret_mode == 'test':
                self.warn('Stripe keys are test-mode keys; no real payments will be taken.')

        if not webhook_secret:
            # Stripe only delivers webhooks to HTTPS URLs, so a site without TLS yet can't have one.
            # Orders are still confirmed by the success page and the reconciliation job (every 15 min).
            self.warn(
                'STRIPE_WEBHOOK_SECRET is not set: orders are only confirmed when the customer returns to the '
                'success page or by the 15-minute reconciliation job. Register a webhook once the site has HTTPS.'
            )
        elif (
            not webhook_secret.startswith('whsec_') or '*' in webhook_secret or _looks_like_placeholder(webhook_secret)
        ):
            self.error('STRIPE_WEBHOOK_SECRET is a placeholder or not a whsec_ signing secret.')

    def check_email(self):
        backend, options = _default_mailer()
        if backend in NON_DELIVERING_EMAIL_BACKENDS:
            self.warn(f'EMAIL_BACKEND is the {backend.split(".")[-2]} backend; no email will be delivered.')
        elif backend == SMTP_BACKEND:
            if not options.get('host'):
                self.error('EMAIL_HOST is not set.')
            user = options.get('username') or ''
            if not user:
                self.error('EMAIL_HOST_USER is not set.')
            elif _looks_like_placeholder(user):
                self.error('EMAIL_HOST_USER is a placeholder.')
            password = options.get('password') or ''
            if not password:
                self.error('EMAIL_HOST_PASSWORD is not set.')
            elif _looks_like_placeholder(password):
                self.error('EMAIL_HOST_PASSWORD is a placeholder.')

        recipient = _value('RECIPIENT_EMAIL') or ''
        if not recipient:
            self.warn('RECIPIENT_EMAIL is not set; contact-form and order-review emails have nowhere to go.')
        elif _looks_like_placeholder(recipient):
            self.warn('RECIPIENT_EMAIL looks like a placeholder.')

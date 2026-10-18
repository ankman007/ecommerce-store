import warnings
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

GOOD_SECRET_KEY = 'k8$Vq2!pZr7wXn4@Lm9#Ty3&Hb6^Jc1*Ue5%Gd0(Sa8)Fo2-Ri7+Pw4=Nz'
STRIPE_SECRET = 'sk_' + 'live_51AbCdEfGhIjKlMnOpQrStUv'
WEBHOOK_SECRET = 'whsec_AbCdEfGhIjKlMnOpQrStUvWxYz123456'
DB_PASSWORD = 'Str0ng-Db-Passw0rd-123'
EMAIL_PASSWORD = 'abcd efgh ijkl mnop'
SMTP_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'


def mailers(backend=SMTP_BACKEND, **options):
    """A MAILERS setting like core/settings.py builds from the EMAIL_* env vars."""
    base = {'host': 'smtp.gmail.com', 'port': 587, 'username': 'orders@shop.test', 'password': EMAIL_PASSWORD}
    return {'default': {'BACKEND': backend, 'OPTIONS': {**base, **options} if backend == SMTP_BACKEND else {}}}


PRODUCTION = dict(
    SECRET_KEY=GOOD_SECRET_KEY,
    DEBUG=False,
    ALLOWED_HOSTS=['shop.test', 'www.shop.test'],
    CSRF_TRUSTED_ORIGINS=['https://shop.test', 'https://www.shop.test'],
    DATABASES={
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': 'ecommerce',
            'USER': 'ecommerce',
            'PASSWORD': DB_PASSWORD,
            'HOST': 'db',
            'PORT': '3306',
        }
    },
    CELERY_BROKER_URL='redis://redis:6379/0',
    CELERY_TASK_ALWAYS_EAGER=False,
    STRIPE_PUBLIC_KEY='pk_live_51AbCdEfGhIjKlMnOpQrStUv',
    STRIPE_SECRET_KEY=STRIPE_SECRET,
    STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET,
    MAILERS=mailers(),
    DEFAULT_FROM_EMAIL='orders@shop.test',
    RECIPIENT_EMAIL='owner@shop.test',
    SESSION_COOKIE_SECURE=True,
    CSRF_COOKIE_SECURE=True,
)


def production(**changes):
    """override_settings for a valid production config with some values changed."""
    return override_settings(**{**PRODUCTION, **changes})


class CheckEnvTests(SimpleTestCase):
    # The test settings use SQLite; DATABASES is overridden, but no query is ever run.
    databases = set()

    def setUp(self):
        # Overriding DATABASES only changes what the command reads; silence Django's caution.
        self.enterContext(warnings.catch_warnings())
        warnings.filterwarnings('ignore', message='Overriding setting DATABASES', category=UserWarning)

    def run_check(self, *args):
        out = StringIO()
        try:
            call_command('check_env', *args, stdout=out)
        except CommandError as exc:
            return False, out.getvalue(), str(exc)
        return True, out.getvalue(), ''

    def assert_fails_with(self, text):
        ok, output, _ = self.run_check()
        self.assertFalse(ok, output)
        self.assertIn(text, output)
        return output

    @production()
    def test_valid_production_config_passes(self):
        ok, output, _ = self.run_check()
        self.assertTrue(ok, output)
        self.assertIn('0 error(s), 0 warning(s)', output)

    @production()
    def test_never_prints_secret_values(self):
        _, output, _ = self.run_check()
        for secret in (GOOD_SECRET_KEY, STRIPE_SECRET, WEBHOOK_SECRET, DB_PASSWORD, EMAIL_PASSWORD):
            self.assertNotIn(secret, output)

    @production(DEBUG=True)
    def test_debug_on_is_an_error(self):
        self.assert_fails_with('DEBUG is on')

    @production(SECRET_KEY='django-insecure-dev-only-key-do-not-use-in-production')
    def test_dev_secret_key_is_an_error(self):
        output = self.assert_fails_with('SECRET_KEY is a development or placeholder value')
        self.assertNotIn('django-insecure', output)

    @production(SECRET_KEY='replace-with-a-long-random-secret')
    def test_placeholder_secret_key_is_an_error(self):
        self.assert_fails_with('SECRET_KEY is a development or placeholder value')

    @production(SECRET_KEY='short-but-random-Xy7')
    def test_short_secret_key_is_an_error(self):
        self.assert_fails_with('SECRET_KEY is too short')

    @production(ALLOWED_HOSTS=['localhost', '127.0.0.1'])
    def test_local_only_allowed_hosts_is_an_error(self):
        self.assert_fails_with('ALLOWED_HOSTS only lists local hosts')

    @production(ALLOWED_HOSTS=['*'])
    def test_wildcard_allowed_hosts_is_an_error(self):
        self.assert_fails_with('ALLOWED_HOSTS contains "*"')

    @production(ALLOWED_HOSTS=['shop.example.com'])
    def test_placeholder_domain_is_an_error(self):
        self.assert_fails_with('ALLOWED_HOSTS still contains placeholder domains')

    @production(CSRF_TRUSTED_ORIGINS=[])
    def test_missing_csrf_trusted_origins_is_an_error(self):
        self.assert_fails_with('CSRF_TRUSTED_ORIGINS is empty')

    @production(CSRF_TRUSTED_ORIGINS=['http://shop.test'])
    def test_http_csrf_origin_is_a_warning(self):
        ok, output, _ = self.run_check()
        self.assertTrue(ok, output)
        self.assertIn('not https://', output)

    @production()
    def test_missing_database_settings_are_errors(self):
        with self.settings(DATABASES={'default': {'ENGINE': 'django.db.backends.mysql', 'NAME': '', 'HOST': ''}}):
            output = self.assert_fails_with('Database NAME is not set (DB_NAME)')
        self.assertIn('Database HOST is not set (DB_HOST)', output)
        self.assertIn('Database PASSWORD is not set (DB_PASSWORD)', output)

    @production()
    def test_sqlite_is_an_error(self):
        with self.settings(DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}):
            self.assert_fails_with('uses SQLite')

    @production(CELERY_BROKER_URL=None)
    def test_missing_broker_is_an_error(self):
        self.assert_fails_with('CELERY_BROKER_URL is not set')

    @production(STRIPE_WEBHOOK_SECRET='')
    def test_missing_webhook_secret_is_a_warning(self):
        # Stripe requires HTTPS for webhooks; an HTTP-only first deploy must still start.
        ok, output, _ = self.run_check()
        self.assertTrue(ok, output)
        self.assertIn('STRIPE_WEBHOOK_SECRET is not set', output)

    @production(STRIPE_WEBHOOK_SECRET='whsec_*************')
    def test_placeholder_webhook_secret_is_an_error(self):
        self.assert_fails_with('STRIPE_WEBHOOK_SECRET is a placeholder')

    @production(STRIPE_PUBLIC_KEY=None, STRIPE_SECRET_KEY='')
    def test_missing_stripe_keys_are_errors(self):
        output = self.assert_fails_with('STRIPE_PUBLIC_KEY is not set')
        self.assertIn('STRIPE_SECRET_KEY is not set', output)

    @production(STRIPE_PUBLIC_KEY='pk_test_51AbCdEfGhIjKlMnOpQrStUv')
    def test_mixed_stripe_modes_is_an_error(self):
        self.assert_fails_with('Stripe keys are from different modes (publishable: test, secret: live)')

    @production(STRIPE_PUBLIC_KEY='pk_test_51AbCdEfGhIjKlMnOpQrStUv', STRIPE_SECRET_KEY='sk_' + 'test_51AbCdEfGhIjKlMn')
    def test_test_mode_keys_are_a_warning(self):
        ok, output, _ = self.run_check()
        self.assertTrue(ok, output)
        self.assertIn('test-mode keys', output)

    @production(STRIPE_PUBLIC_KEY='pk_test_51AbCdEfGhIjKlMnOpQrStUv', STRIPE_SECRET_KEY='sk_' + 'test_51AbCdEfGhIjKlMn')
    def test_fail_on_warning(self):
        ok, output, message = self.run_check('--fail-on-warning')
        self.assertFalse(ok, output)
        self.assertIn('0 error(s), 1 warning(s)', message)

    @production(STRIPE_SECRET_KEY='rk_' + 'live_51AbCdEfGhIjKlMnOpQrStUv')
    def test_restricted_live_key_is_accepted(self):
        ok, output, _ = self.run_check()
        self.assertTrue(ok, output)

    @production(STRIPE_PUBLIC_KEY='not-a-stripe-key')
    def test_malformed_stripe_key_is_an_error(self):
        self.assert_fails_with('does not look like a publishable key')

    @production(MAILERS=mailers(username='', password='replace-with-an-app-password'))
    def test_smtp_credentials_are_checked(self):
        output = self.assert_fails_with('EMAIL_HOST_USER is not set')
        self.assertIn('EMAIL_HOST_PASSWORD is a placeholder', output)

    @production(MAILERS=mailers('django.core.mail.backends.console.EmailBackend'))
    def test_console_email_backend_is_a_warning(self):
        ok, output, _ = self.run_check()
        self.assertTrue(ok, output)
        self.assertIn('EMAIL_BACKEND is the console backend; no email will be delivered', output)

    @production(SESSION_COOKIE_SECURE=False)
    def test_insecure_session_cookie_is_a_warning(self):
        ok, output, _ = self.run_check()
        self.assertTrue(ok, output)
        self.assertIn('SESSION_COOKIE_SECURE is off', output)

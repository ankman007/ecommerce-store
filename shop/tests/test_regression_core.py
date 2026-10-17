"""Regression tests for the project package (core/): settings, logging, entry points, admin bootstrap."""

import io
import logging
import os
import runpy
from contextlib import redirect_stdout
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase

from core import logging_config
from users.models import Profile

SETTINGS_FILE = settings.BASE_DIR / 'core' / 'settings.py'


def load_settings(**env):
    """Execute core/settings.py with exactly ``env`` as the environment (no .env file) and return its globals."""
    env.setdefault('SECRET_KEY', 'x')
    with mock.patch.dict(os.environ, env, clear=True), mock.patch('dotenv.load_dotenv'):
        return runpy.run_path(str(SETTINGS_FILE))


class EnvHelperTests(SimpleTestCase):
    def setUp(self):
        self.ns = load_settings()

    def test_env_bool(self):
        env_bool = self.ns['env_bool']
        for raw, expected in [('1', True), ('true', True), (' Yes ', True), ('on', True), ('0', False), ('no', False)]:
            with mock.patch.dict(os.environ, {'FLAG': raw}):
                self.assertIs(env_bool('FLAG'), expected, raw)
        with mock.patch.dict(os.environ, {'FLAG': '  '}):
            self.assertIs(env_bool('FLAG', True), True)
        self.assertIs(env_bool('UNSET_FLAG_FOR_TEST', True), True)

    def test_env_list(self):
        env_list = self.ns['env_list']
        with mock.patch.dict(os.environ, {'HOSTS': ' a.com, ,b.com ,'}):
            self.assertEqual(env_list('HOSTS'), ['a.com', 'b.com'])
        self.assertEqual(env_list('UNSET_LIST_FOR_TEST', 'x,y'), ['x', 'y'])


class SettingsFromEnvTests(SimpleTestCase):
    def test_secret_key_required_when_debug_off(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch('dotenv.load_dotenv'):
            with self.assertRaises(ImproperlyConfigured):
                runpy.run_path(str(SETTINGS_FILE))

    def test_debug_without_secret_key_uses_dev_key(self):
        with mock.patch.dict(os.environ, {'DEBUG': 'True'}, clear=True), mock.patch('dotenv.load_dotenv'):
            ns = runpy.run_path(str(SETTINGS_FILE))
        self.assertTrue(ns['SECRET_KEY'].startswith('django-insecure-'))
        self.assertFalse(ns['TEMPLATES'][0]['APP_DIRS'])
        self.assertIn('loaders', ns['TEMPLATES'][0]['OPTIONS'])

    def test_production_defaults_are_secure(self):
        ns = load_settings()
        self.assertFalse(ns['DEBUG'])
        self.assertTrue(ns['SESSION_COOKIE_SECURE'])
        self.assertTrue(ns['CSRF_COOKIE_SECURE'])
        self.assertEqual(ns['SECURE_HSTS_SECONDS'], 3600)
        self.assertEqual(ns['X_FRAME_OPTIONS'], 'DENY')
        self.assertEqual(ns['ACCOUNT_DEFAULT_HTTP_PROTOCOL'], 'https')

    def test_db_host_defaults_to_empty_string(self):
        self.assertEqual(load_settings()['DATABASES']['default']['HOST'], '')

    def test_smtp_mailer_built_from_legacy_env_vars(self):
        ns = load_settings(EMAIL_HOST_USER='shop@example.com', EMAIL_HOST_PASSWORD='app-password')
        self.assertEqual(
            ns['MAILERS'],
            {
                'default': {
                    'BACKEND': 'django.core.mail.backends.smtp.EmailBackend',
                    'OPTIONS': {
                        'host': 'smtp.gmail.com',
                        'port': 587,
                        'username': 'shop@example.com',
                        'password': 'app-password',
                        'use_tls': True,
                        'timeout': 30,
                    },
                }
            },
        )
        self.assertEqual(ns['DEFAULT_FROM_EMAIL'], 'shop@example.com')
        self.assertEqual(ns['SERVER_EMAIL'], 'shop@example.com')
        # Deprecated Django 6.1 email settings must not be defined alongside MAILERS.
        for name in ('EMAIL_BACKEND', 'EMAIL_HOST', 'EMAIL_PORT', 'EMAIL_USE_TLS', 'EMAIL_HOST_USER'):
            self.assertNotIn(name, ns)

    def test_smtp_overrides(self):
        ns = load_settings(EMAIL_HOST='mail.example.com', EMAIL_PORT='2525', EMAIL_USE_TLS='false', EMAIL_TIMEOUT='5')
        options = ns['MAILERS']['default']['OPTIONS']
        self.assertEqual(
            (options['host'], options['port'], options['use_tls'], options['timeout']),
            ('mail.example.com', 2525, False, 5),
        )

    def test_non_smtp_backend_gets_no_smtp_options(self):
        ns = load_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend')
        self.assertEqual(
            ns['MAILERS']['default'],
            {'BACKEND': 'django.core.mail.backends.console.EmailBackend', 'OPTIONS': {}},
        )

    def test_default_from_email_precedence(self):
        self.assertEqual(load_settings()['DEFAULT_FROM_EMAIL'], 'webmaster@localhost')
        ns = load_settings(EMAIL_HOST_USER='smtp@example.com', DEFAULT_FROM_EMAIL='Shop <shop@example.com>')
        self.assertEqual(ns['DEFAULT_FROM_EMAIL'], 'Shop <shop@example.com>')

    def test_log_level(self):
        ns = load_settings()
        self.assertEqual(ns['LOG_LEVEL'], 'INFO')
        self.assertEqual(ns['LOGGING']['root']['level'], 'INFO')
        self.assertEqual(ns['LOGGING']['loggers']['kombu']['level'], 'WARNING')
        self.assertEqual(ns['LOGGING']['loggers']['django.request']['level'], 'ERROR')

        ns = load_settings(LOG_LEVEL='critical')
        self.assertEqual(ns['LOGGING']['root']['level'], 'CRITICAL')
        # A stricter LOG_LEVEL also quiets the loggers that are normally capped at WARNING/ERROR.
        self.assertEqual(ns['LOGGING']['loggers']['kombu']['level'], 'CRITICAL')
        self.assertEqual(ns['LOGGING']['loggers']['django.request']['level'], 'CRITICAL')

        with self.assertRaises(ImproperlyConfigured):
            load_settings(LOG_LEVEL='loud')


class LoguruRoutingTests(SimpleTestCase):
    def setUp(self):
        logging_config.route_loguru_to_logging()

    def test_loguru_records_reach_stdlib_logger_of_same_module(self):
        from loguru import logger

        with self.assertLogs(__name__, level='INFO') as captured:
            logger.info('order {} paid', 42)
        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertEqual(record.getMessage(), 'order 42 paid')
        self.assertEqual(record.levelno, logging.INFO)
        self.assertEqual(record.funcName, 'test_loguru_records_reach_stdlib_logger_of_same_module')

    def test_exceptions_carry_exc_info_and_percent_signs_are_literal(self):
        from loguru import logger

        with self.assertLogs(__name__, level='ERROR') as captured:
            try:
                raise ValueError('boom')
            except ValueError:
                logger.exception('100% failed')
        record = captured.records[0]
        self.assertEqual(record.getMessage(), '100% failed')
        self.assertIs(record.exc_info[0], ValueError)

    def test_respects_stdlib_level(self):
        from loguru import logger

        with self.assertLogs(__name__, level=25) as captured:  # 25 = loguru's SUCCESS
            logger.info('hidden')
            logger.success('shown')
            logger.warning('also shown')
        self.assertEqual([r.getMessage() for r in captured.records], ['shown', 'also shown'])
        self.assertEqual(captured.records[0].levelname, 'SUCCESS')

    def test_configure_applies_dict_config_and_routes_loguru(self):
        with (
            mock.patch('logging.config.dictConfig') as dict_config,
            mock.patch.object(logging_config, 'route_loguru_to_logging') as route,
        ):
            logging_config.configure({'version': 1})
        dict_config.assert_called_once_with({'version': 1})
        route.assert_called_once_with()

    def test_active_settings_use_custom_logging_config(self):
        self.assertEqual(settings.LOGGING_CONFIG, 'core.logging_config.configure')


class EntryPointTests(SimpleTestCase):
    def test_wsgi_and_asgi_applications_load(self):
        from core import asgi, wsgi

        self.assertTrue(callable(wsgi.application))
        self.assertTrue(callable(asgi.application))

    def test_celery_app_reads_django_settings(self):
        from core import celery_app

        self.assertEqual(celery_app.main, 'core')
        self.assertIn('expire-stale-checkouts', celery_app.conf.beat_schedule)
        self.assertEqual(celery_app.conf.task_serializer, 'json')
        self.assertFalse(celery_app.conf.worker_hijack_root_logger)
        self.assertTrue(celery_app.conf.task_track_started)
        self.assertTrue(celery_app.conf.worker_send_task_events)


class CreateAdminScriptTests(TestCase):
    def run_main(self, **env):
        from core import create_admin

        out = io.StringIO()
        with mock.patch.dict(os.environ, env), redirect_stdout(out):
            create_admin.main()
        return out.getvalue()

    def test_skips_without_credentials(self):
        output = self.run_main(ADMIN_USERNAME='', ADMIN_PASSWORD='')
        self.assertIn('skipping', output)
        self.assertFalse(User.objects.exists())

    def test_creates_superuser_with_profile_and_is_idempotent(self):
        env = {'ADMIN_USERNAME': ' Boss ', 'ADMIN_EMAIL': 'boss@example.com', 'ADMIN_PASSWORD': 'S3cure-pass!'}
        self.assertIn('created', self.run_main(**env))
        user = User.objects.get()
        self.assertEqual(user.username, 'boss')
        self.assertTrue(user.is_superuser and user.is_staff)
        self.assertTrue(user.check_password('S3cure-pass!'))

        Profile.objects.filter(user=user).delete()
        self.assertIn('already exists', self.run_main(**env))
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(Profile.objects.filter(user=user).exists())

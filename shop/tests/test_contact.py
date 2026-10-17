from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(RECIPIENT_EMAIL='owner@example.com', EMAIL_HOST_USER='noreply@example.com')
class ContactFormTests(TestCase):
    def test_get_renders_form(self):
        resp = self.client.get(reverse('contact'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="message"')

    def test_valid_post_sends_email_and_redirects(self):
        resp = self.client.post(
            reverse('contact'),
            {
                'name': 'Bob',
                'email': 'bob@example.com',
                'subject': 'Hi',
                'message': 'Hello there',
            },
        )
        self.assertRedirects(resp, reverse('home'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn('Bob', msg.subject)
        self.assertIn('bob@example.com', msg.body)
        self.assertIn('Hello there', msg.body)
        self.assertEqual(msg.to, ['owner@example.com'])

    def test_invalid_post_rerenders_with_errors_and_sends_nothing(self):
        resp = self.client.post(
            reverse('contact'),
            {
                'name': '',
                'email': 'not-an-email',
                'message': '',
            },
        )
        self.assertEqual(resp.status_code, 200)
        errors = resp.context['form'].errors
        self.assertIn('email', errors)
        self.assertIn('name', errors)
        self.assertIn('message', errors)
        self.assertEqual(len(mail.outbox), 0)

    def test_static_pages(self):
        for name in ('about', 'privacy_policy', 'contact_success'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

from allauth.account.models import EmailAddress
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from shop.models import Order
from shop.tests.helpers import PASSWORD, make_user
from users.models import Profile

LOGIN_REQUIRED_URLS = [
    'orders', 'profile-edit', 'profile-onboarding', 'profile-settings',
    'profile-emailchange', 'profile-usernamechange', 'profile-emailverify',
    'profile-delete',
]


class LoginRequiredTests(TestCase):
    def test_anonymous_redirected_to_login(self):
        login_url = reverse('account_login')
        for name in LOGIN_REQUIRED_URLS:
            url = reverse(name)
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, name)
            self.assertTrue(resp['Location'].startswith(login_url), name)
            self.assertIn('next=', resp['Location'], name)

    def test_anonymous_own_profile_redirects_to_login(self):
        resp = self.client.get('/profile/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('account_login'), resp['Location'])

    def test_anonymous_post_delete_does_not_delete(self):
        make_user('alice')
        self.client.post(reverse('profile-delete'))
        self.assertTrue(User.objects.filter(username='alice').exists())


class AuthTests(TestCase):
    def test_login_with_email(self):
        make_user('alice')
        resp = self.client.post(reverse('account_login'), {
            'login': 'alice@example.com', 'password': PASSWORD,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_login_wrong_password(self):
        make_user('alice')
        resp = self.client.post(reverse('account_login'), {
            'login': 'alice@example.com', 'password': 'wrong',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)


class ProfileSignalTests(TestCase):
    def test_profile_auto_created(self):
        user = make_user('alice')
        self.assertTrue(Profile.objects.filter(user=user).exists())
        self.assertEqual(user.profile.name, 'alice')

    def test_username_lowercased(self):
        user = User.objects.create_user('MixedCase', 'm@example.com', PASSWORD)
        self.assertEqual(user.username, 'mixedcase')

    def test_profile_deleted_with_user(self):
        user = make_user('alice')
        user.delete()
        self.assertFalse(Profile.objects.exists())

    def test_avatar_default(self):
        self.assertIn('avatar.svg', make_user('alice').profile.avatar)


class ProfileViewTests(TestCase):
    def setUp(self):
        self.user = make_user('alice')
        self.other = make_user('bob')
        EmailAddress.objects.create(user=self.user, email=self.user.email, primary=True, verified=True)
        self.client.force_login(self.user)

    def test_own_profile(self):
        resp = self.client.get(reverse('profile'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['profile'], self.user.profile)

    def test_public_profile_by_username(self):
        resp = self.client.get('/@bob/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['profile'], self.other.profile)

    def test_unknown_public_profile_404(self):
        self.assertEqual(self.client.get('/@nobody/').status_code, 404)

    def test_profile_edit_get(self):
        resp = self.client.get(reverse('profile-edit'))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['onboarding'])
        self.assertTrue(self.client.get(reverse('profile-onboarding')).context['onboarding'])

    def test_profile_edit_post_updates_only_own_profile(self):
        resp = self.client.post(reverse('profile-edit'), {'displayname': 'Ally', 'info': 'Hi'})
        self.assertRedirects(resp, reverse('profile'), fetch_redirect_response=False)
        self.user.profile.refresh_from_db()
        self.other.profile.refresh_from_db()
        self.assertEqual(self.user.profile.displayname, 'Ally')
        self.assertEqual(self.user.profile.info, 'Hi')
        self.assertIsNone(self.other.profile.displayname)

    def test_settings_page(self):
        self.assertEqual(self.client.get(reverse('profile-settings')).status_code, 200)

    def test_username_change(self):
        resp = self.client.post(reverse('profile-usernamechange'), {'username': 'alicia'})
        self.assertRedirects(resp, reverse('profile-settings'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'alicia')

    def test_username_change_to_taken_name_rejected(self):
        self.client.post(reverse('profile-usernamechange'), {'username': 'bob'})
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'alice')

    def test_username_change_htmx_returns_form(self):
        resp = self.client.get(reverse('profile-usernamechange'), HTTP_HX_REQUEST='true')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="username"')

    def test_email_change_triggers_verification_email(self):
        resp = self.client.post(reverse('profile-emailchange'), {'email': 'new@example.com'})
        self.assertRedirects(resp, reverse('profile-settings'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.com')
        addr = EmailAddress.objects.get_primary(self.user)
        self.assertEqual(addr.email, 'new@example.com')
        self.assertFalse(addr.verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('new@example.com', mail.outbox[0].to)

    def test_email_change_to_taken_email_rejected(self):
        self.client.post(reverse('profile-emailchange'), {'email': 'bob@example.com'})
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'alice@example.com')
        self.assertEqual(len(mail.outbox), 0)

    def test_email_change_invalid_email_rejected(self):
        self.client.post(reverse('profile-emailchange'), {'email': 'not-an-email'})
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'alice@example.com')

    def test_email_verify_resends_for_unverified_address(self):
        EmailAddress.objects.filter(user=self.user).update(verified=False)
        self.client.get(reverse('profile-emailverify'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('alice@example.com', mail.outbox[0].to)

    def test_email_verify_skipped_for_verified_address(self):
        self.client.get(reverse('profile-emailverify'))
        self.assertEqual(len(mail.outbox), 0)

    def test_delete_get_shows_confirmation_without_deleting(self):
        resp = self.client.get(reverse('profile-delete'))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_delete_post_deletes_only_self_and_logs_out(self):
        resp = self.client.post(reverse('profile-delete'))
        self.assertRedirects(resp, reverse('home'), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.other.pk).exists())
        self.assertNotIn('_auth_user_id', self.client.session)


class OrderVisibilityTests(TestCase):
    def test_user_sees_only_own_orders(self):
        alice = make_user('alice')
        bob = make_user('bob')
        mine = Order.objects.create(user=alice, paid=True)
        theirs = Order.objects.create(user=bob, paid=True)
        self.client.force_login(alice)
        resp = self.client.get(reverse('orders'))
        self.assertEqual(resp.status_code, 200)
        orders = list(resp.context['orders'])
        self.assertIn(mine, orders)
        self.assertNotIn(theirs, orders)

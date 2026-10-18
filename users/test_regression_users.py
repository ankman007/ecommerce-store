"""Regression tests for users edge cases: profile form validation, signals, settings views."""

import os
from io import BytesIO

from allauth.account.models import EmailAddress
from django.contrib.auth.models import User
from django.core import mail
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from shop.tests.helpers import PASSWORD, make_image_file, make_user
from users.forms import MAX_AVATAR_SIZE, ProfileForm
from users.models import Profile
from users.signals import user_postsave


def noise_png(min_bytes):
    """A valid PNG larger than ``min_bytes`` (random pixels don't compress)."""
    side = int((min_bytes / 3) ** 0.5) + 50
    buf = BytesIO()
    Image.frombytes('RGB', (side, side), os.urandom(side * side * 3)).save(buf, format='PNG')
    return SimpleUploadedFile('big.png', buf.getvalue(), content_type='image/png')


class ProfileFormTests(TestCase):
    def setUp(self):
        self.profile = make_user().profile

    def form(self, data=None, image=None):
        files = {'image': image} if image else {}
        return ProfileForm(data or {}, files, instance=self.profile)

    def test_valid_image_and_blank_fields_become_none(self):
        form = self.form({'displayname': '   ', 'info': '  '}, make_image_file('me.png'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data['displayname'])
        self.assertIsNone(form.cleaned_data['info'])

    def test_oversized_image_rejected(self):
        image = noise_png(MAX_AVATAR_SIZE + 1)
        self.assertGreater(image.size, MAX_AVATAR_SIZE)
        form = self.form(image=image)
        self.assertFalse(form.is_valid())
        self.assertIn('too large', form.errors['image'][0])

    def test_unsupported_extension_rejected(self):
        image = make_image_file('avatar.bmp')  # real image data, extension Pillow accepts but we don't
        form = self.form(image=image)
        self.assertFalse(form.is_valid())
        self.assertIn('Unsupported image type', form.errors['image'][0])

    def test_long_info_rejected(self):
        form = self.form({'info': 'x' * 1001})
        self.assertFalse(form.is_valid())
        self.assertIn('1000 characters', form.errors['info'][0])


class ProfileModelTests(TestCase):
    def test_name_and_avatar(self):
        user = make_user('alice')
        profile = user.profile
        self.assertEqual(str(profile), 'alice')
        self.assertEqual(profile.name, 'alice')
        self.assertTrue(profile.avatar.endswith('images/avatar.svg'))

        profile.displayname = 'Alice A.'
        profile.image = make_image_file('a.png')
        profile.save()
        self.assertEqual(profile.name, 'Alice A.')
        self.assertIn('avatars/', profile.avatar)


class UserSignalTests(TestCase):
    def test_raw_save_skips_profile_creation(self):
        user = make_user('alice')
        Profile.objects.filter(user=user).delete()
        user_postsave(sender=User, instance=user, created=True, raw=True)
        self.assertFalse(Profile.objects.filter(user=user).exists())

    def test_existing_secondary_address_is_promoted(self):
        user = make_user('alice')
        old = EmailAddress.objects.create(user=user, email='alice@example.com', primary=True, verified=True)
        new = EmailAddress.objects.create(user=user, email='work@example.com', primary=False, verified=True)
        user.email = 'WORK@example.com'
        user.save()
        old.refresh_from_db()
        new.refresh_from_db()
        self.assertFalse(old.primary)
        self.assertTrue(new.primary)
        self.assertTrue(new.verified)

    def test_first_address_created_when_none_exists(self):
        user = make_user('alice')
        user.email = 'alice2@example.com'
        user.save()
        addr = EmailAddress.objects.get(user=user)
        self.assertTrue(addr.primary)
        self.assertFalse(addr.verified)

    def test_clearing_email_leaves_addresses_alone(self):
        user = make_user('alice')
        EmailAddress.objects.create(user=user, email='alice@example.com', primary=True, verified=True)
        user.email = ''
        user.save()
        self.assertTrue(EmailAddress.objects.get(user=user).primary)


class SettingsViewEdgeCaseTests(TestCase):
    def setUp(self):
        self.user = make_user('alice')
        EmailAddress.objects.create(user=self.user, email='alice@example.com', primary=True, verified=True)
        self.client.login(email='alice@example.com', password=PASSWORD)

    def test_htmx_get_returns_partials_and_plain_get_redirects(self):
        htmx = {'HX-Request': 'true'}
        for name, field in (('profile-emailchange', 'email'), ('profile-usernamechange', 'username')):
            url = reverse(name)
            self.assertContains(self.client.get(url, headers=htmx), f'name="{field}"')
            self.assertRedirects(self.client.get(url), reverse('profile-settings'), fetch_redirect_response=False)

    def test_unchanged_email_is_a_no_op(self):
        resp = self.client.post(reverse('profile-emailchange'), {'email': 'alice@example.com'})
        self.assertRedirects(resp, reverse('profile-settings'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(list(get_messages(resp.wsgi_request)), [])

    def test_username_change_lowercases_and_rejects_taken(self):
        make_user('bob')
        self.client.post(reverse('profile-usernamechange'), {'username': 'NewName'})
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'newname')
        self.client.post(reverse('profile-usernamechange'), {'username': 'BOB'})
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'newname')

    def test_superuser_cannot_delete_self_here(self):
        self.user.is_superuser = True
        self.user.save()
        resp = self.client.post(reverse('profile-delete'), follow=True)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertContains(resp, 'cannot be deleted')

    def test_profile_by_username_is_case_insensitive_and_404s(self):
        self.assertEqual(self.client.get('/@ALICE/').status_code, 200)
        self.assertEqual(self.client.get('/@nobody/').status_code, 404)

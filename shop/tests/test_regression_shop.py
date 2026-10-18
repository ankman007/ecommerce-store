"""Regression tests for shop code paths the feature tests don't reach (tasks, utils, admin, models, seeding)."""

import io
from decimal import Decimal
from smtplib import SMTPException
from unittest import mock

import stripe
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.sites.models import Site
from django.core import mail
from django.core.management import call_command
from django.db import IntegrityError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from shop.admin import OrderItemInline
from shop.forms import ContactForm
from shop.models import Cart, CartItem, Order, OrderItem, Payment, ProductImage
from shop.signals import merge_guest_cart_on_login
from shop.tasks import notify_order_needs_review, send_contact_email
from shop.tests.helpers import make_category, make_image_file, make_product, make_user
from shop.utils import check_product_for_cart, get_user_cart


@override_settings(DEFAULT_FROM_EMAIL='noreply@example.com', SERVER_EMAIL='server@example.com')
class EmailTaskTests(TestCase):
    @override_settings(RECIPIENT_EMAIL='owner@example.com')
    def test_contact_email_is_sent_from_default_from_email(self):
        send_contact_email('bob@example.com', 'Hello', 'Body text')
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.from_email, 'noreply@example.com')
        self.assertEqual(msg.to, ['owner@example.com'])
        self.assertIn('From: <bob@example.com>', msg.body)

    @override_settings(RECIPIENT_EMAIL='owner@example.com')
    def test_review_email_goes_to_shop_inbox(self):
        notify_order_needs_review(7, 'Stock ran out')
        msg = mail.outbox[0]
        self.assertEqual(msg.from_email, 'noreply@example.com')
        self.assertEqual(msg.subject, 'Order #7 needs review')
        self.assertIn('Stock ran out', msg.body)

    @override_settings(RECIPIENT_EMAIL=None, ADMINS=['admin@example.com'])
    def test_review_email_falls_back_to_admins(self):
        notify_order_needs_review(8, 'Amount mismatch')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['admin@example.com'])
        self.assertEqual(mail.outbox[0].from_email, 'server@example.com')
        self.assertIn('Order #8 needs review', mail.outbox[0].subject)

    @override_settings(RECIPIENT_EMAIL=None, ADMINS=[])
    def test_review_email_without_any_recipient_is_a_no_op(self):
        notify_order_needs_review(9, 'x')
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(RECIPIENT_EMAIL=None, ADMINS=['admin@example.com'])
    def test_admin_mail_failure_is_logged_not_raised(self):
        with (
            mock.patch('shop.tasks.mail_admins', side_effect=SMTPException('down')),
            mock.patch('shop.tasks.logger') as logger,
        ):
            notify_order_needs_review(10, 'x')
        logger.exception.assert_called_once()


class CartUtilsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_lost_create_race_returns_whatever_the_winner_created(self):
        user = make_user()
        with mock.patch.object(Cart.objects, 'create', side_effect=IntegrityError):
            # The concurrent request's cart is not visible here, so the fallback lookup finds nothing.
            self.assertIsNone(get_user_cart(user, create=True))

    def test_without_create_no_cart_is_made(self):
        user = make_user()
        self.assertIsNone(get_user_cart(user))
        self.assertFalse(Cart.objects.exists())

    def test_check_product_for_cart(self):
        user = make_user()
        request = self.factory.get('/')
        request.user = user
        request.session = {}
        self.assertEqual(check_product_for_cart(request), set())

        anon = self.factory.get('/')
        anon.user = AnonymousUser()
        anon.session = {'cart': ['not', 'a', 'dict']}
        self.assertEqual(check_product_for_cart(anon), set())
        anon.session = {'cart': {'abc': 1, 5: 2}}
        self.assertEqual(check_product_for_cart(anon), {'abc', '5'})

    def test_merge_signal_ignores_missing_request(self):
        user = make_user()
        self.assertIsNone(merge_guest_cart_on_login(sender=None, request=None, user=user))
        self.assertFalse(Cart.objects.exists())


class ModelStrTests(TestCase):
    def test_string_representations(self):
        user = make_user('alice')
        category = make_category('Books')
        product = make_product('Novel', price='12.50', category=category)
        cart = Cart.objects.create(user=user)
        item = CartItem.objects.create(cart=cart, product=product, quantity=2)
        payment = Payment.objects.create(user=user, total_price=Decimal('25.00'))
        order = Order.objects.create(user=user)
        line = OrderItem.objects.create(order=order, product=None, quantity=1, price=Decimal('3.00'))

        self.assertEqual(str(category), 'Category: Books')
        self.assertEqual(category.slug, 'books')
        self.assertEqual(str(product), 'Product: Novel (Category: Books)')
        self.assertEqual(str(make_product('Loose')), 'Product: Loose (Category: Uncategorized)')
        self.assertTrue(str(cart).startswith('Cart for alice - Created at '))
        self.assertEqual(str(item), '2 x Novel (Subtotal: $25.00)')
        self.assertIn('Status: Pending', str(payment))
        self.assertEqual(str(order), f'Order #{order.pk} by alice')
        self.assertEqual(str(line), '1 x Deleted product')
        self.assertEqual(line.subtotal(), Decimal('3.00'))

    def test_resaving_an_image_does_not_recompress_it(self):
        product = make_product()
        image = ProductImage.objects.create(product=product, images=make_image_file())
        name = image.images.name
        self.assertEqual(image.alt_text, 'widget')
        self.assertFalse(image.has_changed_image())
        image.alt_text = 'Front'
        image.save()
        image.refresh_from_db()
        self.assertEqual(image.images.name, name)
        self.assertTrue(ProductImage(product=product).has_changed_image())


class ContactFormTests(TestCase):
    def test_header_injection_is_rejected(self):
        form = ContactForm(
            data={
                'name': 'Bob\nBcc: x@y.z',
                'email': 'bob@example.com',
                'subject': 'Hi\r\nBcc: x@y.z',
                'message': 'Long enough text',
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)
        self.assertIn('subject', form.errors)


class AdminPagesTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser('boss', 'boss@example.com', 'S3cure-pass!')
        self.client.force_login(self.admin_user)
        customer = make_user('carol')
        self.product = make_product(with_image=True, category=make_category())
        cart = Cart.objects.create(user=customer)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        Payment.objects.create(user=customer, total_price=Decimal('10.00'))
        self.order = Order.objects.create(
            user=customer, paid=True, status=Order.STATUS_PAID, stripe_payment_intent='pi_1', total=Decimal('10.00')
        )
        OrderItem.objects.create(order=self.order, product=self.product, quantity=2, price=Decimal('5.00'))

    def test_every_registered_model_admin_renders(self):
        for model, model_admin in admin.site._registry.items():
            opts = model._meta
            with self.subTest(model=opts.label):
                changelist = reverse(f'admin:{opts.app_label}_{opts.model_name}_changelist')
                self.assertEqual(self.client.get(changelist).status_code, 200)
                self.assertEqual(self.client.get(changelist, {'q': 'x'}).status_code, 200)
                try:
                    add_url = reverse(f'admin:{opts.app_label}_{opts.model_name}_add')
                except NoReverseMatch:
                    continue
                self.assertEqual(self.client.get(add_url).status_code, 200)
                obj = model._default_manager.first()
                if obj is not None:
                    change_url = reverse(f'admin:{opts.app_label}_{opts.model_name}_change', args=[obj.pk])
                    self.assertEqual(self.client.get(change_url).status_code, 200)

    def test_order_change_page_shows_line_totals(self):
        url = reverse('admin:a_shop_order_change', args=[self.order.pk])
        resp = self.client.get(url)
        self.assertContains(resp, '10.00')
        inline = OrderItemInline(Order, admin.site)
        self.assertEqual(inline.line_total(OrderItem()), '-')
        self.assertFalse(inline.has_add_permission(resp.wsgi_request))

    @mock.patch('shop.views.payment.stripe.Refund.create', side_effect=stripe.StripeError('card issue'))
    def test_refund_action_reports_stripe_errors(self, create):
        resp = self.client.post(
            reverse('admin:a_shop_order_changelist'),
            {'action': 'refund_via_stripe', '_selected_action': [self.order.pk]},
            follow=True,
        )
        self.assertContains(resp, 'Stripe refused the refund')
        self.assertNotContains(resp, 'Refunded 1 order')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PAID)


class SeedDemoDataTests(TestCase):
    def test_seeds_catalog_and_customer_idempotently(self):
        from allauth.account.models import EmailAddress

        from shop.management.commands.seed_demo_data import CATALOG, CUSTOMER_EMAIL, CUSTOMER_PASSWORD
        from shop.models import Product

        expected = sum(len(products) for _, _, products in CATALOG)
        call_command('seed_demo_data', stdout=io.StringIO())
        self.assertEqual(Product.objects.count(), expected)
        self.assertTrue(ProductImage.objects.exists())
        self.assertEqual(Site.objects.get(id=1).name, 'Ecommerce Store')
        customer = User.objects.get(username='customer')
        self.assertTrue(customer.check_password(CUSTOMER_PASSWORD))
        self.assertTrue(EmailAddress.objects.get(user=customer, email=CUSTOMER_EMAIL).verified)

        call_command('seed_demo_data', stdout=io.StringIO())
        self.assertEqual(Product.objects.count(), expected)

        out = io.StringIO()
        call_command('seed_demo_data', '--reset', stdout=out)
        self.assertIn('Removed', out.getvalue())
        self.assertEqual(Product.objects.count(), expected)


class GuestCartEdgeCaseTests(TestCase):
    def setUp(self):
        self.product = make_product(stock=3)

    def set_session_cart(self, value):
        session = self.client.session
        session['cart'] = value
        session.save()

    def test_legacy_and_junk_session_values_are_tolerated(self):
        other = make_product('Gadget')
        self.set_session_cart({self.product.id: {'quantity': 2, 'price': '10.00'}, other.id: 'junk', 'gone': 1})
        resp = self.client.get(reverse('cart'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([i['quantity'] for i in resp.context['cart_items']], [2])

        self.set_session_cart(['not', 'a', 'dict'])
        self.assertEqual(self.client.get(reverse('cart')).context['cart_items'], [])

    def test_update_requires_post(self):
        resp = self.client.get(reverse('update_cart_item', args=[self.product.id]))
        self.assertRedirects(resp, reverse('cart'), fetch_redirect_response=False)

    def test_guest_update_caps_by_stock_and_zero_removes(self):
        self.set_session_cart({self.product.id: 1})
        url = reverse('update_cart_item', args=[self.product.id])
        self.client.post(url, {'quantity': '99'})
        self.assertEqual(self.client.session['cart'], {self.product.id: 3})
        self.client.post(url, {'quantity': 'abc'})  # invalid -> 1
        self.assertEqual(self.client.session['cart'], {self.product.id: 1})
        self.client.post(url, {'quantity': '0'})
        self.assertEqual(self.client.session['cart'], {})

    def test_guest_update_ignores_products_not_in_cart(self):
        self.set_session_cart({})
        self.client.post(reverse('update_cart_item', args=[self.product.id]), {'quantity': '2'})
        self.assertEqual(self.client.session['cart'], {})


class PaymentEdgeCaseTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.product = make_product(stock=5)
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1)

    @mock.patch('shop.views.payment.stripe.checkout.Session.create', side_effect=stripe.StripeError('down'))
    def test_session_creation_failure_cancels_order(self, create):
        address = {
            'full_name': 'Test Buyer',
            'phone': '+1 518 555 0100',
            'address_line1': '1 Main St',
            'city': 'Albany',
            'state': 'NY',
            'postal_code': '12206',
            'country': 'US',
        }
        resp = self.client.post(reverse('checkout'), address)
        self.assertRedirects(resp, reverse('cart'), fetch_redirect_response=False)
        self.assertEqual(Order.objects.get().status, Order.STATUS_CANCELLED)

    @mock.patch('shop.views.payment.stripe.checkout.Session.retrieve', side_effect=stripe.StripeError('down'))
    def test_success_page_survives_stripe_outage(self, retrieve):
        order = Order.objects.create(user=self.user, stripe_session_id='cs_1')
        resp = self.client.get(reverse('success'), {'session_id': 'cs_1'})
        self.assertRedirects(resp, reverse('orders'), fetch_redirect_response=False)
        order.refresh_from_db()
        self.assertFalse(order.paid)

    def test_success_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse('success'), {'session_id': 'cs_1'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('account_login'), resp['Location'])

    def test_fulfil_and_cancel_guard_clauses(self):
        from shop.views.payment import cancel_unpaid_order, fulfill_checkout_session

        self.assertEqual(fulfill_checkout_session({'payment_status': 'paid'}), (None, 'not_found'))
        self.assertEqual(fulfill_checkout_session({'id': 'cs_x', 'payment_status': 'unpaid'}), (None, 'unpaid'))
        self.assertEqual(fulfill_checkout_session({'id': 'cs_x', 'payment_status': 'paid'}), (None, 'not_found'))
        self.assertIsNone(cancel_unpaid_order(None))
        self.assertIsNone(cancel_unpaid_order('cs_unknown'))

"""Phase 1 payment safety: constraints, race-safe cart writes, session expiry, review flow, refunds."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import stripe
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from shop.models import Cart, CartItem, Order, OrderItem
from shop.tasks import expire_stale_checkouts
from shop.utils import change_cart_line, get_user_cart
from shop.views.payment import CHECKOUT_SESSION_TTL, fulfill_checkout_session, refund_order

from .helpers import make_product, make_user
from .test_checkout import CheckoutBase, FakeSession


class ConstraintTests(TestCase):
    def test_one_line_per_product_per_cart(self):
        cart = Cart.objects.create(user=make_user())
        product = make_product()
        CartItem.objects.create(cart=cart, product=product, quantity=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CartItem.objects.create(cart=cart, product=product, quantity=1)

    def test_stripe_session_id_is_unique_but_nullable(self):
        Order.objects.create(stripe_session_id='cs_dup')
        Order.objects.create()
        Order.objects.create()  # several orders without a session are fine
        with self.assertRaises(IntegrityError), transaction.atomic():
            Order.objects.create(stripe_session_id='cs_dup')


class CartLineTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.cart = get_user_cart(self.user, create=True)
        self.product = make_product(stock=5)

    def test_get_user_cart_create_is_idempotent(self):
        self.assertEqual(get_user_cart(self.user, create=True), self.cart)
        self.assertEqual(Cart.objects.filter(user=self.user).count(), 1)

    def test_adds_accumulate_and_are_capped_by_stock(self):
        self.assertEqual(change_cart_line(self.cart, self.product, add=2), (0, 2))
        self.assertEqual(change_cart_line(self.cart, self.product, add=2), (2, 4))
        self.assertEqual(change_cart_line(self.cart, self.product, add=10), (4, 5))
        self.assertEqual(CartItem.objects.get(cart=self.cart).quantity, 5)

    def test_set_and_zero_removes(self):
        change_cart_line(self.cart, self.product, quantity=3)
        self.assertEqual(change_cart_line(self.cart, self.product, quantity=0), (3, 0))
        self.assertFalse(CartItem.objects.filter(cart=self.cart).exists())


class SessionCreationTests(CheckoutBase):
    def test_session_expires_after_ttl(self):
        before = timezone.now()
        _, create = self.checkout()
        expires_at = create.call_args.kwargs['expires_at']
        expected = (before + CHECKOUT_SESSION_TTL).timestamp()
        self.assertAlmostEqual(expires_at, expected, delta=5)


@override_settings(RECIPIENT_EMAIL='shop@example.com', EMAIL_HOST_USER='noreply@example.com')
class ReviewFlowTests(CheckoutBase):
    def setUp(self):
        super().setUp()
        self.checkout()
        self.order = Order.objects.get()

    def fulfil(self, **kwargs):
        session = self.paid_session(**kwargs)
        session['payment_intent'] = 'pi_test_1'
        with self.captureOnCommitCallbacks(execute=True):
            return fulfill_checkout_session(session)

    def test_records_payment_intent(self):
        self.fulfil()
        self.order.refresh_from_db()
        self.assertEqual(self.order.stripe_payment_intent, 'pi_test_1')
        self.assertEqual(self.order.status, Order.STATUS_PAID)
        self.assertEqual(len(mail.outbox), 0)

    def test_oversold_order_is_flagged_and_shop_emailed(self):
        self.product.stock = 1  # sold elsewhere while the customer was paying for 2
        self.product.save()
        _, result = self.fulfil()
        self.assertEqual(result, 'paid')
        self.order.refresh_from_db()
        self.assertTrue(self.order.paid)
        self.assertEqual(self.order.status, Order.STATUS_NEEDS_REVIEW)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(f'#{self.order.id}', mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ['shop@example.com'])

    def test_amount_mismatch_is_flagged_but_not_paid(self):
        _, result = self.fulfil(amount=1)
        self.assertEqual(result, 'amount_mismatch')
        self.order.refresh_from_db()
        self.assertFalse(self.order.paid)
        self.assertEqual(self.order.status, Order.STATUS_NEEDS_REVIEW)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)
        self.assertEqual(len(mail.outbox), 1)


class ExpiryWebhookTests(CheckoutBase):
    def setUp(self):
        super().setUp()
        self.checkout()
        self.order = Order.objects.get()

    def send(self, event_type):
        event = {'type': event_type, 'data': {'object': {'id': 'cs_test_1'}}}
        with (
            self.settings(STRIPE_WEBHOOK_SECRET='whsec_test'),
            patch('shop.views.payment.stripe.Webhook.construct_event', return_value=event),
        ):
            return self.client.post(
                reverse('stripe_webhook'), data=b'{}', content_type='application/json', HTTP_STRIPE_SIGNATURE='t=1,v1=x'
            )

    def test_expired_session_cancels_pending_order(self):
        self.assertEqual(self.send('checkout.session.expired').status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_CANCELLED)

    def test_expiry_never_cancels_a_paid_order(self):
        self.order.paid = True
        self.order.status = Order.STATUS_PAID
        self.order.save()
        self.send('checkout.session.expired')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PAID)


class StaleCheckoutTaskTests(CheckoutBase):
    def make_pending(self, session_id, age=timedelta(hours=3)):
        order = Order.objects.create(user=self.user, stripe_session_id=session_id, total=Decimal('25.00'))
        OrderItem.objects.create(order=order, product=self.product, quantity=2, price=Decimal('10.00'))
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - age)
        return order

    def run_task(self, sessions):
        def retrieve(session_id):
            return sessions[session_id]

        with (
            patch('stripe.checkout.Session.retrieve', side_effect=retrieve),
            patch('stripe.checkout.Session.expire') as expire,
        ):
            counts = expire_stale_checkouts()
        return counts, expire

    def test_resolves_each_stale_order_by_asking_stripe(self):
        open_order = self.make_pending('cs_open')
        expired_order = self.make_pending('cs_expired')
        paid_order = self.make_pending('cs_paid')
        recent = self.make_pending('cs_recent', age=timedelta(minutes=5))
        no_session = self.make_pending(None)

        counts, expire = self.run_task(
            {
                'cs_open': FakeSession(id='cs_open', status='open', payment_status='unpaid'),
                'cs_expired': FakeSession(id='cs_expired', status='expired', payment_status='unpaid'),
                'cs_paid': FakeSession(
                    id='cs_paid', status='complete', payment_status='paid', amount_total=2500, payment_intent='pi_late'
                ),
            }
        )

        expire.assert_called_once_with('cs_open')
        for order, status in [
            (open_order, Order.STATUS_CANCELLED),
            (expired_order, Order.STATUS_CANCELLED),
            (no_session, Order.STATUS_CANCELLED),
            (paid_order, Order.STATUS_PAID),  # missed webhook still gets fulfilled
            (recent, Order.STATUS_PENDING),  # customer may still be paying
        ]:
            order.refresh_from_db()
            self.assertEqual(order.status, status, order.stripe_session_id)
        self.assertEqual(counts, {'fulfilled': 1, 'cancelled': 3, 'errors': 0})

    def test_stripe_errors_leave_order_pending(self):
        order = self.make_pending('cs_broken')
        with patch('stripe.checkout.Session.retrieve', side_effect=stripe.APIConnectionError('down')):
            counts = expire_stale_checkouts()
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PENDING)
        self.assertEqual(counts['errors'], 1)


class RefundTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.order = Order.objects.create(
            user=self.user,
            paid=True,
            status=Order.STATUS_NEEDS_REVIEW,
            stripe_payment_intent='pi_123',
            total=Decimal('25.00'),
        )

    @patch('shop.views.payment.stripe.Refund.create')
    def test_refund_is_idempotent_and_marks_order(self, create):
        refund_order(self.order)
        create.assert_called_once_with(payment_intent='pi_123', idempotency_key=f'refund-order-{self.order.pk}')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_REFUNDED)

    @patch('shop.views.payment.stripe.Refund.create')
    def test_refuses_unpaid_or_untraceable_orders(self, create):
        pending = Order.objects.create(status=Order.STATUS_PENDING, stripe_payment_intent='pi_x')
        no_pi = Order.objects.create(status=Order.STATUS_PAID, paid=True)
        for order in (pending, no_pi):
            with self.assertRaises(ValueError):
                refund_order(order)
        create.assert_not_called()

    def admin_action(self, action, orders):
        admin_user = make_user('boss')
        admin_user.is_staff = admin_user.is_superuser = True
        admin_user.save()
        self.client.force_login(admin_user)
        return self.client.post(
            reverse('admin:a_shop_order_changelist'),
            {'action': action, '_selected_action': [o.pk for o in orders]},
            follow=True,
        )

    @patch('shop.views.payment.stripe.Refund.create')
    def test_admin_refund_action(self, create):
        pending = Order.objects.create(status=Order.STATUS_PENDING)
        resp = self.admin_action('refund_via_stripe', [self.order, pending])
        self.assertContains(resp, 'Refunded 1 order(s)')
        self.assertContains(resp, f'Order #{pending.pk} not refunded')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_REFUNDED)

    def test_admin_mark_reviewed_action(self):
        self.admin_action('mark_reviewed', [self.order])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PAID)

    def test_customer_sees_refunded_badge(self):
        self.order.status = Order.STATUS_REFUNDED
        self.order.save()
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('orders')), 'Refunded')

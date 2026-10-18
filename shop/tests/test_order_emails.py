"""Customer emails: order confirmation (once), shipped and refunded notifications."""

from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from shop.models import Order, OrderItem
from shop.tasks import send_order_confirmation, send_order_status_email
from shop.tests.helpers import make_product, make_user
from shop.views.order import mark_order_shipped
from shop.views.payment import fulfill_checkout_session, refund_order

from .test_checkout import FakeSession


@override_settings(DEFAULT_FROM_EMAIL='orders@shop.test', SITE_URL='https://shop.test')
class OrderEmailTests(TestCase):
    def setUp(self):
        self.user = make_user('carol')
        self.product = make_product(name='Blue Kettle', price='10.00', stock=5)
        self.order = Order.objects.create(
            user=self.user,
            stripe_session_id='cs_mail_1',
            shipping_cost=Decimal('5.00'),
            total=Decimal('25.00'),
            full_name='Carol Customer',
            phone='+1 518 555 0199',
            address_line1='5 State St',
            city='Albany',
            state='NY',
            postal_code='12207',
            country='US',
        )
        OrderItem.objects.create(order=self.order, product=self.product, quantity=2, price=Decimal('10.00'))

    def paid_session(self):
        return FakeSession(id='cs_mail_1', payment_status='paid', amount_total=2500, payment_intent='pi_mail_1')

    def fulfil(self):
        with self.captureOnCommitCallbacks(execute=True):
            return fulfill_checkout_session(self.paid_session())

    def test_confirmation_sent_once_after_fulfilment(self):
        _, result = self.fulfil()
        self.assertEqual(result, 'paid')
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['carol@example.com'])
        self.assertEqual(message.from_email, 'orders@shop.test')
        self.assertIn(f'#{self.order.id}', message.subject)
        self.assertIn('Blue Kettle', message.body)
        self.assertIn('$25.00', message.body)
        self.assertIn('5 State St', message.body)
        self.assertIn(f'https://shop.test/orders/{self.order.id}/', message.body)
        html, mimetype = message.alternatives[0]
        self.assertEqual(mimetype, 'text/html')
        self.assertIn('Blue Kettle', html)
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.confirmation_sent_at)

        # Re-fulfilment (duplicate webhook, success redirect, cleanup task) never re-sends.
        _, result = self.fulfil()
        self.assertEqual(result, 'already_paid')
        send_order_confirmation(self.order.id)
        self.assertEqual(len(mail.outbox), 1)

    def test_confirmation_sent_via_signed_webhook(self):
        event = {'type': 'checkout.session.completed', 'data': {'object': self.paid_session()}}
        with (
            self.settings(STRIPE_WEBHOOK_SECRET='whsec_test'),
            patch('shop.views.payment.stripe.Webhook.construct_event', return_value=event),
            self.captureOnCommitCallbacks(execute=True),
        ):
            for _ in range(2):  # Stripe may deliver the same event twice
                response = self.client.post(
                    reverse('stripe_webhook'), b'{}', content_type='application/json', HTTP_STRIPE_SIGNATURE='sig'
                )
                self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['carol@example.com'])

    def test_no_confirmation_for_unpaid_or_mismatched_orders(self):
        self.assertFalse(send_order_confirmation(self.order.id))
        session = self.paid_session()
        session['amount_total'] = 1
        with self.captureOnCommitCallbacks(execute=True):
            fulfill_checkout_session(session)
        self.assertEqual([m for m in mail.outbox if m.to == ['carol@example.com']], [])

    def test_no_email_address_is_skipped_quietly(self):
        self.user.email = ''
        self.user.save()
        self.fulfil()
        self.assertEqual(len(mail.outbox), 0)

    def test_failed_send_releases_the_claim(self):
        Order.objects.filter(pk=self.order.pk).update(paid=True)
        with patch('shop.tasks.EmailMultiAlternatives.send', side_effect=OSError('smtp down')):
            with self.assertRaises(OSError):
                send_order_confirmation(self.order.id)
        self.order.refresh_from_db()
        self.assertIsNone(self.order.confirmation_sent_at)
        self.assertTrue(send_order_confirmation(self.order.id))
        self.assertEqual(len(mail.outbox), 1)

    def test_shipped_email_with_tracking_number(self):
        self.fulfil()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            mark_order_shipped(self.order, tracking_number=' 1Z999AA10123456784 ')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_SHIPPED)
        self.assertIsNotNone(self.order.shipped_at)
        self.assertEqual(self.order.tracking_number, '1Z999AA10123456784')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('shipped', mail.outbox[0].subject)
        self.assertIn('1Z999AA10123456784', mail.outbox[0].body)
        self.assertIn('1Z999AA10123456784', mail.outbox[0].alternatives[0][0])

    def test_unpaid_order_cannot_be_shipped(self):
        with self.assertRaises(ValueError), self.captureOnCommitCallbacks(execute=True):
            mark_order_shipped(self.order)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PENDING)
        self.assertEqual(len(mail.outbox), 0)

    def test_refund_email(self):
        self.fulfil()
        mail.outbox.clear()
        self.order.refresh_from_db()
        with (
            patch('shop.views.payment.stripe.Refund.create') as refund,
            self.captureOnCommitCallbacks(execute=True),
        ):
            refund_order(self.order)
        refund.assert_called_once()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('refunded', mail.outbox[0].subject)
        self.assertIn('$25.00', mail.outbox[0].body)

    def test_status_email_for_missing_order_is_noop(self):
        self.assertFalse(send_order_status_email(999999, 'shipped'))

    @override_settings(SITE_URL=None, DEFAULT_FROM_EMAIL='shop@fallback.test')
    def test_falls_back_to_sites_framework_and_default_from(self):
        Order.objects.filter(pk=self.order.pk).update(paid=True)
        send_order_confirmation(self.order.id)
        message = mail.outbox[0]
        self.assertEqual(message.from_email, 'shop@fallback.test')
        self.assertIn(f'://example.com/orders/{self.order.id}/', message.body)

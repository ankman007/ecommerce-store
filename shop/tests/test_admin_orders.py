"""Admin order management: mark shipped, tracking numbers, address display, existing actions."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from shop.models import Order, OrderItem
from shop.tests.helpers import make_product, make_user


class AdminOrderTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('boss', 'boss@example.com', 'pw')
        self.client.force_login(self.admin)
        self.customer = make_user('dave')
        self.product = make_product(name='Red Mug', price='8.00', stock=3)
        self.order = self.make_order()

    def make_order(self, status=Order.STATUS_PAID, paid=True, **extra):
        order = Order.objects.create(
            user=self.customer,
            status=status,
            paid=paid,
            paid_at=timezone.now() if paid else None,
            shipping_cost=Decimal('5.00'),
            total=Decimal('21.00'),
            full_name='Dave Doe',
            phone='+1 518 555 0111',
            address_line1='9 River Rd',
            city='Troy',
            state='NY',
            postal_code='12180',
            country='US',
            stripe_payment_intent='pi_admin_1' if paid else None,
            **extra,
        )
        OrderItem.objects.create(order=order, product=self.product, quantity=2, price=Decimal('8.00'))
        return order

    def run_action(self, action, orders):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                reverse('admin:a_shop_order_changelist'),
                {'action': action, '_selected_action': [o.pk for o in orders]},
                follow=True,
            )

    def test_changelist_and_search(self):
        response = self.client.get(reverse('admin:a_shop_order_changelist'), {'q': '12180'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'>{self.order.pk}<')
        self.assertContains(response, 'Mark as shipped')

    def test_change_page_shows_address_totals_and_customer_link(self):
        response = self.client.get(reverse('admin:a_shop_order_change', args=[self.order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '9 River Rd')
        self.assertContains(response, 'Troy, NY 12180')
        self.assertContains(response, '+1 518 555 0111')
        self.assertContains(response, reverse('admin:auth_user_change', args=[self.customer.pk]))
        self.assertContains(response, '16.00')  # subtotal
        self.assertContains(response, 'name="tracking_number"')
        # The address snapshot is read-only.
        self.assertNotContains(response, 'name="address_line1"')

    def test_mark_shipped_action(self):
        Order.objects.filter(pk=self.order.pk).update(tracking_number='TRACK123')
        pending = self.make_order(status=Order.STATUS_PENDING, paid=False)
        response = self.run_action('mark_shipped', [self.order, pending])
        self.assertContains(response, 'Marked 1 order(s) as shipped')
        self.assertContains(response, f'Order #{pending.pk} not shipped')
        self.order.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_SHIPPED)
        self.assertIsNotNone(self.order.shipped_at)
        self.assertEqual(pending.status, Order.STATUS_PENDING)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['dave@example.com'])
        self.assertIn('TRACK123', mail.outbox[0].body)

    def test_needs_review_orders_are_not_shipped(self):
        Order.objects.filter(pk=self.order.pk).update(status=Order.STATUS_NEEDS_REVIEW)
        self.run_action('mark_shipped', [self.order])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_NEEDS_REVIEW)
        self.assertEqual(len(mail.outbox), 0)

    def test_setting_status_to_shipped_in_form_records_and_emails(self):
        item = self.order.items.get()
        data = {
            'user': self.customer.pk,
            'status': Order.STATUS_SHIPPED,
            'paid': 'on',
            'tracking_number': 'ZX-42',
            'items-TOTAL_FORMS': '1',
            'items-INITIAL_FORMS': '1',
            'items-MIN_NUM_FORMS': '0',
            'items-MAX_NUM_FORMS': '1000',
            'items-0-id': str(item.pk),
            'items-0-order': str(self.order.pk),
        }
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('admin:a_shop_order_change', args=[self.order.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_SHIPPED)
        self.assertEqual(self.order.tracking_number, 'ZX-42')
        self.assertIsNotNone(self.order.shipped_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('ZX-42', mail.outbox[0].body)

        # Saving again (already shipped) doesn't email again.
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('admin:a_shop_order_change', args=[self.order.pk]), data)
        self.assertEqual(len(mail.outbox), 1)

    def test_refund_action_still_works_and_emails_customer(self):
        with patch('shop.views.payment.stripe.Refund.create') as refund:
            self.run_action('refund_via_stripe', [self.order])
        refund.assert_called_once_with(payment_intent='pi_admin_1', idempotency_key=f'refund-order-{self.order.pk}')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_REFUNDED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('refunded', mail.outbox[0].subject)

    def test_shipped_orders_can_be_refunded(self):
        self.run_action('mark_shipped', [self.order])
        with patch('shop.views.payment.stripe.Refund.create'):
            self.run_action('refund_via_stripe', [self.order])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_REFUNDED)

    def test_mark_reviewed_still_works(self):
        Order.objects.filter(pk=self.order.pk).update(status=Order.STATUS_NEEDS_REVIEW)
        self.run_action('mark_reviewed', [self.order])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_PAID)

    def test_order_without_address_or_user(self):
        legacy = Order.objects.create(user=None, paid=True, status=Order.STATUS_PAID)
        response = self.client.get(reverse('admin:a_shop_order_change', args=[legacy.pk]))
        self.assertContains(response, 'No address collected')
        self.assertEqual(self.client.get(reverse('admin:a_shop_order_changelist')).status_code, 200)

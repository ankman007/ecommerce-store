from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.test import TestCase, RequestFactory
from django.urls import reverse

from shop.models import Cart, CartItem, Order, OrderItem, Product
from shop.views.cart import SHIPPING_COST
from shop.views.payment import fulfill_checkout_session


class FakeSession(dict):
    """Behaves like a StripeObject: item and attribute access."""
    __getattr__ = dict.get


def make_product(name='Widget', price='10.00', stock=5):
    return Product.objects.create(name=name, price=Decimal(price), stock=stock, description='d')


class CheckoutBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', 'alice@example.com', 'pw')
        self.client.force_login(self.user)
        self.product = make_product(price='10.00', stock=5)
        self.cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)

    def checkout(self, data=None, session_id='cs_test_1'):
        with patch('shop.views.payment.stripe.checkout.Session.create') as create:
            create.return_value = FakeSession(id=session_id, url='https://checkout.stripe.test/pay')
            resp = self.client.post(reverse('checkout'), data or {})
        return resp, create

    def paid_session(self, session_id='cs_test_1', amount=None, status='paid'):
        if amount is None:
            amount = int((Decimal('20.00') + SHIPPING_COST) * 100)
        return FakeSession(id=session_id, payment_status=status, amount_total=amount)


class CreateCheckoutTests(CheckoutBase):
    def test_get_redirects_to_cart(self):
        resp = self.client.get(reverse('checkout'))
        self.assertRedirects(resp, reverse('cart'), fetch_redirect_response=False)

    def test_creates_pending_order_from_db_cart_and_ignores_posted_prices(self):
        resp, create = self.checkout({'items_name': ['Widget'], 'items_price': ['0.01'], 'items_quantity': ['99']})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], 'https://checkout.stripe.test/pay')
        kwargs = create.call_args.kwargs
        product_line = kwargs['line_items'][0]
        self.assertEqual(product_line['price_data']['unit_amount'], 1000)
        self.assertEqual(product_line['quantity'], 2)
        shipping_line = kwargs['line_items'][1]
        self.assertEqual(shipping_line['price_data']['unit_amount'], int(SHIPPING_COST * 100))
        self.assertIn('{CHECKOUT_SESSION_ID}', kwargs['success_url'])
        order = Order.objects.get()
        self.assertEqual(order.stripe_session_id, 'cs_test_1')
        self.assertFalse(order.paid)
        self.assertEqual(order.status, Order.STATUS_PENDING)
        self.assertEqual(order.total, Decimal('20.00') + SHIPPING_COST)
        item = order.items.get()
        self.assertEqual((item.quantity, item.price), (2, Decimal('10.00')))
        # stock untouched until payment is confirmed
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)

    def test_out_of_stock_refused(self):
        self.product.stock = 1
        self.product.save()
        resp, create = self.checkout()
        self.assertRedirects(resp, reverse('cart'), fetch_redirect_response=False)
        create.assert_not_called()
        self.assertFalse(Order.objects.exists())

    def test_empty_cart_refused(self):
        self.cart.items.all().delete()
        resp, create = self.checkout()
        self.assertRedirects(resp, reverse('cart'), fetch_redirect_response=False)
        create.assert_not_called()

    def test_anonymous_post_redirects_to_login(self):
        self.client.logout()
        resp, create = self.checkout()
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('account_login'), resp['Location'])
        create.assert_not_called()

    def test_duplicate_carts_do_not_crash(self):
        Cart.objects.create(user=self.user)
        resp = self.client.get(reverse('cart'))
        self.assertEqual(resp.status_code, 200)


class SuccessTests(CheckoutBase):
    def setUp(self):
        super().setUp()
        self.checkout()
        self.order = Order.objects.get()

    def visit_success(self, stripe_session, session_id='cs_test_1'):
        with patch('shop.views.payment.stripe.checkout.Session.retrieve', return_value=stripe_session) as r:
            resp = self.client.get(reverse('success'), {'session_id': session_id})
        return resp, r

    def test_forged_success_without_session_id_rejected(self):
        resp = self.client.get(reverse('success'))
        self.assertEqual(resp.status_code, 302)
        self.order.refresh_from_db()
        self.assertFalse(self.order.paid)

    def test_forged_unknown_session_rejected(self):
        self.visit_success(self.paid_session('cs_forged'), session_id='cs_forged')
        self.order.refresh_from_db()
        self.assertFalse(self.order.paid)
        self.assertEqual(Order.objects.filter(paid=True).count(), 0)

    def test_session_of_other_user_rejected(self):
        other = User.objects.create_user('bob', 'bob@example.com', 'pw')
        self.client.force_login(other)
        self.visit_success(self.paid_session())
        self.order.refresh_from_db()
        self.assertFalse(self.order.paid)

    def test_unpaid_session_rejected(self):
        resp, _ = self.visit_success(self.paid_session(status='unpaid'))
        self.assertRedirects(resp, reverse('cart'), fetch_redirect_response=False)
        self.order.refresh_from_db()
        self.assertFalse(self.order.paid)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)

    def test_amount_mismatch_rejected(self):
        self.visit_success(self.paid_session(amount=100))
        self.order.refresh_from_db()
        self.assertFalse(self.order.paid)

    def test_paid_session_marks_paid_exactly_once(self):
        resp, _ = self.visit_success(self.paid_session())
        self.assertRedirects(
            resp, reverse('order_detail', args=[self.order.id]) + '?placed=1', fetch_redirect_response=False
        )
        self.order.refresh_from_db()
        self.assertTrue(self.order.paid)
        self.assertEqual(self.order.status, Order.STATUS_PAID)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self.assertFalse(CartItem.objects.filter(cart__user=self.user).exists())

        # Second visit / duplicate webhook: no double processing.
        self.visit_success(self.paid_session())
        _, result = fulfill_checkout_session(self.paid_session())
        self.assertEqual(result, 'already_paid')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self.assertEqual(Order.objects.count(), 1)

    def test_stock_never_negative_when_oversold(self):
        Product.objects.filter(pk=self.product.pk).update(stock=1)  # concurrent purchase
        _, result = fulfill_checkout_session(self.paid_session())
        self.assertEqual(result, 'paid')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0)


class WebhookTests(CheckoutBase):
    def setUp(self):
        super().setUp()
        self.checkout()

    def post_webhook(self, signature='t=1,v1=x'):
        return self.client.post(reverse('stripe_webhook'), data='{}', content_type='application/json',
                                HTTP_STRIPE_SIGNATURE=signature)

    def test_no_secret_configured_rejects(self):
        with self.settings(STRIPE_WEBHOOK_SECRET=None), patch.dict('os.environ', {'STRIPE_WEBHOOK_SECRET': ''}):
            resp = self.post_webhook()
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Order.objects.get().paid)

    def test_bad_signature_rejected(self):
        with self.settings(STRIPE_WEBHOOK_SECRET='whsec_test'):
            resp = self.post_webhook('t=1,v1=bad')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Order.objects.get().paid)

    def test_signed_completed_event_marks_paid(self):
        event = {'type': 'checkout.session.completed', 'data': {'object': self.paid_session()}}
        with self.settings(STRIPE_WEBHOOK_SECRET='whsec_test'), \
                patch('shop.views.payment.stripe.Webhook.construct_event', return_value=event):
            resp = self.post_webhook('t=1,v1=ok')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Order.objects.get().paid)


class CartTests(TestCase):
    def setUp(self):
        self.product = make_product(stock=3)

    def test_add_to_cart_caps_quantity_at_stock(self):
        resp = self.client.post(reverse('add_to_cart', args=[self.product.id]), {'quantity': 10})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('cart-count', resp.content.decode())
        self.assertEqual(self.client.session['cart'][self.product.id], 3)

    def test_add_to_cart_rejects_invalid_quantity(self):
        for bad in ('-1', '0', 'abc'):
            self.client.post(reverse('add_to_cart', args=[self.product.id]), {'quantity': bad})
        self.assertNotIn(self.product.id, self.client.session.get('cart', {}))

    def test_add_out_of_stock_rejected(self):
        p = make_product(name='Gone', stock=0)
        resp = self.client.post(reverse('add_to_cart', args=[p.id]), {'quantity': 1})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('out of stock', resp.content.decode().lower())
        self.assertNotIn(p.id, self.client.session.get('cart', {}))

    def test_cart_page_uses_single_shipping_constant(self):
        self.client.post(reverse('add_to_cart', args=[self.product.id]), {'quantity': 1})
        resp = self.client.get(reverse('cart'))
        self.assertEqual(resp.context['shipping_cost'], SHIPPING_COST)
        self.assertEqual(resp.context['total'], Decimal('10.00') + SHIPPING_COST)

    def test_update_quantity(self):
        user = User.objects.create_user('u', 'u@example.com', 'pw')
        self.client.force_login(user)
        self.client.post(reverse('add_to_cart', args=[self.product.id]), {'quantity': 1})
        resp = self.client.post(reverse('update_cart_item', args=[self.product.id]), {'quantity': 2})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(CartItem.objects.get().quantity, 2)

    def test_guest_cart_merged_on_login(self):
        from allauth.account.signals import user_logged_in
        user = User.objects.create_user('carol', 'carol@example.com', 'pw')
        cart = Cart.objects.create(user=user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        other = make_product(name='Other', stock=10)

        request = RequestFactory().get('/')
        request.session = SessionStore()
        request.session['cart'] = {self.product.id: 5, other.id: 2}
        user_logged_in.send(sender=User, request=request, user=user)

        self.assertEqual(CartItem.objects.get(cart=cart, product=self.product).quantity, 3)  # capped by stock
        self.assertEqual(CartItem.objects.get(cart=cart, product=other).quantity, 2)
        self.assertEqual(request.session['cart'], {})


class OrderItemStrTests(TestCase):
    def test_str_with_deleted_product(self):
        order = Order.objects.create()
        item = OrderItem.objects.create(order=order, product=None, quantity=1, price=Decimal('1.00'))
        self.assertIn('Deleted product', str(item))

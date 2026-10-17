"""Storefront UX: shared footer data, order pages, cancel flow and add-to-cart feedback."""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from shop.models import Order, OrderItem

from .helpers import make_category, make_product, make_user


class FooterTests(TestCase):
    def setUp(self):
        make_category('Books')
        make_category('Garden')

    def test_footer_lists_categories_on_static_pages(self):
        for name in ('about', 'contact', 'privacy_policy'):
            with self.subTest(page=name):
                resp = self.client.get(reverse(name))
                self.assertContains(resp, reverse('category', args=['books']))
                self.assertContains(resp, reverse('category', args=['garden']))
                self.assertNotContains(resp, 'No categories found')

    def test_footer_shows_current_year(self):
        resp = self.client.get(reverse('about'))
        self.assertContains(resp, f'&copy; {timezone.now().year}')


class OrderPagesTests(TestCase):
    def setUp(self):
        self.user = make_user('alice')
        self.product = make_product(name='Lamp', price='20.00')
        self.order = Order.objects.create(
            user=self.user, paid=True, status=Order.STATUS_PAID, paid_at=timezone.now(),
            shipping_cost=Decimal('5.00'), total=Decimal('45.00'),
        )
        OrderItem.objects.create(order=self.order, product=self.product, quantity=2, price=Decimal('20.00'))

    def test_owner_sees_order_detail(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('order_detail', args=[self.order.id]))
        self.assertContains(resp, 'Lamp')
        self.assertContains(resp, '$45.00')
        self.assertNotContains(resp, 'Thank you for your order')

    def test_confirmation_message_after_checkout(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('order_detail', args=[self.order.id]) + '?placed=1')
        self.assertContains(resp, 'Thank you for your order')

    def test_other_users_order_is_404(self):
        self.client.force_login(make_user('bob'))
        resp = self.client.get(reverse('order_detail', args=[self.order.id]))
        self.assertEqual(resp.status_code, 404)

    def test_unpaid_order_is_404(self):
        pending = Order.objects.create(user=self.user, status=Order.STATUS_PENDING)
        self.client.force_login(self.user)
        resp = self.client.get(reverse('order_detail', args=[pending.id]))
        self.assertEqual(resp.status_code, 404)

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse('order_detail', args=[self.order.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('account_login'), resp['Location'])

    def test_orders_list_links_to_detail(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('orders'))
        self.assertContains(resp, reverse('order_detail', args=[self.order.id]))


class CheckoutCancelTests(TestCase):
    def test_cancel_returns_to_cart(self):
        resp = self.client.get(reverse('cancel'))
        self.assertRedirects(resp, reverse('cart'), fetch_redirect_response=False)


class AddToCartFeedbackTests(TestCase):
    def test_toast_names_product_and_escapes_it(self):
        product = make_product(name='<b>Bold</b> Mug', stock=5)
        resp = self.client.post(reverse('add_to_cart', args=[product.id]), {'quantity': 1})
        body = resp.content.decode()
        self.assertIn('&lt;b&gt;Bold&lt;/b&gt; Mug', body)
        self.assertNotIn('<b>Bold</b>', body)
        self.assertIn('View cart', body)

    def test_product_cards_offer_add_to_cart(self):
        make_product(name='Kettle', stock=3)
        make_product(name='Sold Out Thing', stock=0)
        resp = self.client.get(reverse('home'))
        self.assertContains(resp, 'Add to cart')
        self.assertContains(resp, 'Out of stock')

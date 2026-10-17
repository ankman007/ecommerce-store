from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from shop.models import Cart, CartItem
from shop.tests.helpers import make_product, make_user

HTMX = {'HTTP_HX_REQUEST': 'true'}


class CartTestMixin:
    def add(self, product, qty=1, **extra):
        return self.client.post(reverse('add_to_cart', args=[product.id]), {'quantity': qty}, **extra)


class GuestCartTests(CartTestMixin, TestCase):
    def setUp(self):
        self.p1 = make_product('Mug', price='8.00', stock=20)
        self.p2 = make_product('Plate', price='5.50', stock=20)

    def test_add_stores_in_session(self):
        resp = self.add(self.p1, 2)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.session['cart'], {self.p1.id: 2})
        self.assertFalse(CartItem.objects.exists())

    def test_add_same_product_twice_accumulates(self):
        self.add(self.p1, 1)
        self.add(self.p1, 2)
        self.assertEqual(self.client.session['cart'][self.p1.id], 3)

    def test_cart_count_in_context(self):
        self.add(self.p1, 2)
        self.add(self.p2, 1)
        resp = self.client.get(reverse('cart'))
        self.assertEqual(resp.context['cart_count'], 3)

    def test_htmx_response_contains_button_count_and_toast(self):
        resp = self.add(self.p1, 1, **HTMX)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('id="cart-count"', body)
        self.assertIn('hx-swap-oob', body)
        self.assertIn('class="custom-toast', body)
        self.assertIn('hx-swap-oob="beforeend:#toast-region"', body)
        self.assertIn('Added', body)
        self.assertIn('/cart/', body)

    def test_cart_count_fragment_shows_total(self):
        self.add(self.p1, 2)
        resp = self.add(self.p2, 3, **HTMX)
        self.assertRegex(resp.content.decode(), r'id="cart-count"[^>]*>\s*5\s*<')

    def test_cart_page_subtotal_and_total(self):
        self.add(self.p1, 2)  # 16.00
        self.add(self.p2, 1)  # 5.50
        resp = self.client.get(reverse('cart'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(str(resp.context['subtotal'])), Decimal('21.50'))
        self.assertGreater(float(resp.context['total']), 21.50)  # includes shipping
        self.assertContains(resp, 'Mug')
        self.assertContains(resp, 'Plate')

    def test_empty_cart_page(self):
        resp = self.client.get(reverse('cart'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['subtotal'], 0)

    def test_remove_from_session(self):
        self.add(self.p1, 1)
        self.add(self.p2, 1)
        resp = self.client.post(reverse('remove_from_cart', args=[self.p1.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.p1.id, self.client.session['cart'])
        self.assertIn(self.p2.id, self.client.session['cart'])

    def test_add_unknown_product_404(self):
        resp = self.client.post(reverse('add_to_cart', args=['missing1']), {'quantity': 1})
        self.assertEqual(resp.status_code, 404)

    def test_remove_unknown_product_404(self):
        self.assertEqual(self.client.post(reverse('remove_from_cart', args=['missing1'])).status_code, 404)

    def test_get_add_to_cart_does_not_change_cart(self):
        resp = self.client.get(reverse('add_to_cart', args=[self.p1.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(self.client.session.get('cart'))

    def test_get_remove_does_not_change_cart(self):
        self.add(self.p1, 1)
        resp = self.client.get(reverse('remove_from_cart', args=[self.p1.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(self.p1.id, self.client.session['cart'])


class AuthenticatedCartTests(CartTestMixin, TestCase):
    def setUp(self):
        self.user = make_user('alice')
        self.other = make_user('bob')
        self.p1 = make_product('Mug', price='8.00', stock=20)
        self.p2 = make_product('Plate', price='5.50', stock=20)
        self.client.force_login(self.user)

    def test_add_creates_db_cart_item(self):
        resp = self.add(self.p1, 2, **HTMX)
        self.assertEqual(resp.status_code, 200)
        item = CartItem.objects.get(cart__user=self.user, product=self.p1)
        self.assertEqual(item.quantity, 2)
        self.assertIn('id="cart-count"', resp.content.decode())

    def test_add_twice_increments(self):
        self.add(self.p1, 1)
        self.add(self.p1, 3)
        self.assertEqual(CartItem.objects.get(cart__user=self.user, product=self.p1).quantity, 4)
        self.assertEqual(CartItem.objects.filter(cart__user=self.user).count(), 1)

    def test_remove_deletes_db_item(self):
        self.add(self.p1, 1)
        self.add(self.p2, 1)
        resp = self.client.post(reverse('remove_from_cart', args=[self.p1.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(CartItem.objects.filter(cart__user=self.user, product=self.p1).exists())
        self.assertTrue(CartItem.objects.filter(cart__user=self.user, product=self.p2).exists())

    def test_cart_page_subtotal(self):
        self.add(self.p1, 3)  # 24.00
        self.add(self.p2, 2)  # 11.00
        resp = self.client.get(reverse('cart'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Decimal(str(resp.context['subtotal'])), Decimal('35.00'))
        self.assertEqual(resp.context['cart_count'], 5)

    def test_cart_isolated_between_users(self):
        other_cart = Cart.objects.create(user=self.other)
        CartItem.objects.create(cart=other_cart, product=self.p2, quantity=7)
        self.add(self.p1, 1)
        resp = self.client.get(reverse('cart'))
        self.assertContains(resp, 'Mug')
        self.assertNotContains(resp, 'Plate')
        self.assertEqual(resp.context['cart_count'], 1)

    def test_cannot_remove_other_users_item(self):
        other_cart = Cart.objects.create(user=self.other)
        CartItem.objects.create(cart=other_cart, product=self.p2, quantity=7)
        self.client.post(reverse('remove_from_cart', args=[self.p2.id]))
        self.assertEqual(CartItem.objects.get(cart=other_cart, product=self.p2).quantity, 7)

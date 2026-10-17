"""Checkout step 1: shipping address + phone, stored as a snapshot on the order."""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from shop.models import Cart, CartItem, Order
from shop.tests.helpers import make_product, make_user

from .test_checkout import FakeSession

ADDRESS = {
    'full_name': 'Alice Example',
    'phone': '+1 (518) 555-0100',
    'address_line1': '1 Main St',
    'address_line2': 'Apt 2',
    'city': 'Albany',
    'state': 'NY',
    'postal_code': '12207',
    'country': 'US',
}


class CheckoutAddressTests(TestCase):
    def setUp(self):
        self.user = make_user('alice')
        self.client.force_login(self.user)
        self.product = make_product(price='10.00', stock=5)
        self.cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)

    def post(self, data, url_name='checkout_address', session_id='cs_addr_1'):
        with patch('shop.views.payment.stripe.checkout.Session.create') as create:
            create.return_value = FakeSession(id=session_id, url='https://checkout.stripe.test/pay')
            response = self.client.post(reverse(url_name), data)
        return response, create

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        response = self.client.get(reverse('checkout_address'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('account_login'), response['Location'])
        self.assertIn('next=/checkout/', response['Location'])

    def test_empty_cart_redirects_to_cart(self):
        self.cart.items.all().delete()
        response = self.client.get(reverse('checkout_address'))
        self.assertRedirects(response, reverse('cart'), fetch_redirect_response=False)

    def test_get_shows_form_and_summary(self):
        response = self.client.get(reverse('checkout_address'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'a_shop/checkout.html')
        self.assertContains(response, 'name="address_line1"')
        self.assertContains(response, 'name="phone"')
        self.assertContains(response, '25.00')  # 2 x 10.00 + 5.00 shipping
        self.assertContains(response, 'noindex')
        self.assertEqual(response.context['form'].initial.get('country'), 'US')

    def test_cart_page_links_to_address_step(self):
        response = self.client.get(reverse('cart'))
        self.assertContains(response, f'action="{reverse("checkout_address")}"')

    def test_valid_post_creates_order_with_snapshot_and_sends_shipping_to_stripe(self):
        response, create = self.post(ADDRESS)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'https://checkout.stripe.test/pay')
        order = Order.objects.get()
        self.assertEqual(order.full_name, 'Alice Example')
        self.assertEqual(order.phone, '+1 (518) 555-0100')
        self.assertEqual(order.address_line1, '1 Main St')
        self.assertEqual(order.address_line2, 'Apt 2')
        self.assertEqual((order.city, order.state, order.postal_code, order.country), ('Albany', 'NY', '12207', 'US'))
        self.assertEqual(order.total, Decimal('25.00'))
        shipping = create.call_args.kwargs['payment_intent_data']['shipping']
        self.assertEqual(shipping['name'], 'Alice Example')
        self.assertEqual(shipping['phone'], '+1 (518) 555-0100')
        self.assertEqual(shipping['address']['line1'], '1 Main St')
        self.assertEqual(shipping['address']['country'], 'US')
        # Prices still come from the DB cart only.
        self.assertEqual(create.call_args.kwargs['line_items'][0]['price_data']['unit_amount'], 1000)

    def test_missing_fields_rerender_form_without_calling_stripe(self):
        data = {**ADDRESS, 'phone': '', 'address_line1': ''}
        response, create = self.post(data)
        self.assertEqual(response.status_code, 400)
        create.assert_not_called()
        self.assertFalse(Order.objects.exists())
        form = response.context['form']
        self.assertIn('phone', form.errors)
        self.assertIn('address_line1', form.errors)
        self.assertContains(response, 'Alice Example', status_code=400)  # input is kept

    def test_invalid_phone_and_postal_code_rejected(self):
        response, create = self.post({**ADDRESS, 'phone': 'call me maybe', 'postal_code': '!!'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('phone', response.context['form'].errors)
        self.assertIn('postal_code', response.context['form'].errors)
        create.assert_not_called()

    def test_state_required_only_for_us(self):
        response, create = self.post({**ADDRESS, 'state': ''})
        self.assertEqual(response.status_code, 400)
        self.assertIn('state', response.context['form'].errors)
        response, create = self.post({**ADDRESS, 'state': '', 'country': 'GB', 'postal_code': 'sw1a 1aa'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Order.objects.get().postal_code, 'SW1A 1AA')

    def test_unknown_country_rejected(self):
        response, create = self.post({**ADDRESS, 'country': 'XX'})
        self.assertEqual(response.status_code, 400)
        create.assert_not_called()

    def test_header_injection_in_name_rejected(self):
        response, create = self.post({**ADDRESS, 'full_name': 'Alice\nBcc: x@example.com'})
        self.assertEqual(response.status_code, 400)
        create.assert_not_called()

    def test_legacy_checkout_post_without_address_shows_form(self):
        response, create = self.post({}, url_name='checkout')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'a_shop/checkout.html')
        create.assert_not_called()
        self.assertFalse(Order.objects.exists())

    def test_stock_is_checked_before_address(self):
        self.product.stock = 1
        self.product.save()
        response, create = self.post(ADDRESS)
        self.assertRedirects(response, reverse('cart'), fetch_redirect_response=False)
        create.assert_not_called()

    def test_form_prefilled_from_last_order(self):
        self.post(ADDRESS)
        response = self.client.get(reverse('checkout_address'))
        initial = response.context['form'].initial
        self.assertEqual(initial['address_line1'], '1 Main St')
        self.assertEqual(initial['phone'], '+1 (518) 555-0100')
        self.assertContains(response, 'value="1 Main St"')

    def test_prefill_never_uses_another_users_address(self):
        self.post(ADDRESS)
        bob = make_user('bob')
        Cart.objects.create(user=bob).items.create(product=self.product, quantity=1)
        self.client.force_login(bob)
        response = self.client.get(reverse('checkout_address'))
        self.assertNotIn('address_line1', response.context['form'].initial)
        self.assertNotContains(response, '1 Main St')

    def test_snapshot_survives_later_orders(self):
        self.post(ADDRESS, session_id='cs_a')
        first = Order.objects.get()
        self.post({**ADDRESS, 'address_line1': '99 New Rd'}, session_id='cs_b')
        first.refresh_from_db()
        self.assertEqual(first.address_line1, '1 Main St')
        self.assertEqual(Order.objects.exclude(pk=first.pk).get().address_line1, '99 New Rd')

    def test_order_detail_shows_address(self):
        self.post(ADDRESS)
        order = Order.objects.get()
        Order.objects.filter(pk=order.pk).update(paid=True, status=Order.STATUS_PAID)
        response = self.client.get(reverse('order_detail', args=[order.id]))
        self.assertContains(response, 'Shipping to')
        self.assertContains(response, '1 Main St')
        self.assertContains(response, 'Albany, NY 12207')
        self.assertContains(response, 'United States')
        self.assertContains(response, '+1 (518) 555-0100')

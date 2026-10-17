"""Query-count guards for read paths. Bounds are independent of product count (no N+1)."""

import os
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from shop.models import Cart, CartItem, Category, Order, OrderItem, Product, ProductImage

# 1x1 GIF; ProductImage.save() re-encodes it to JPEG via Pillow.
GIF = (
    b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00\x00\x00\x00\x00,'
    b'\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
)


class ReadPathQueryCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.categories = [Category.objects.create(name=f'Cat {i}') for i in range(3)]
        cls.products = []
        for i in range(15):
            p = Product.objects.create(
                name=f'Product {i}',
                description='desc',
                price=Decimal('9.99'),
                stock=5,
                category=cls.categories[i % 3],
            )
            for j in range(2):
                ProductImage.objects.create(
                    product=p, images=SimpleUploadedFile(f'p{i}_{j}.gif', GIF, content_type='image/gif')
                )
            cls.products.append(p)
        cls.user = User.objects.create_user('perf', password='pw12345!')

    def count(self, url):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        if os.environ.get('QDBG'):
            print(url, *[q['sql'][:110] for q in ctx.captured_queries], sep=chr(10) + '  ')
        return len(ctx.captured_queries), response

    def assertMaxQueries(self, url, maximum):
        n, response = self.count(url)
        self.assertLessEqual(n, maximum, f'{url} ran {n} queries (max {maximum})')
        return response

    # Logged-in pages also include session, user and a_users profile (header) queries.
    # Anonymous: products + images prefetch + categories (+ session) — no per-product queries.
    def test_home(self):
        response = self.assertMaxQueries(reverse('home'), 5)
        # Paginated since 0006 (12 per page); the bound must hold for later pages too.
        self.assertEqual(len(response.context['products']), 12)
        self.assertEqual(response.context['paginator'].count, 15)
        response = self.assertMaxQueries(reverse('home') + '?page=2&sort=price_desc&in_stock=1', 5)
        self.assertEqual(len(response.context['products']), 3)

    def test_category(self):
        self.assertMaxQueries(reverse('category', args=[self.categories[0].slug]), 6)

    def test_search(self):
        self.assertMaxQueries(reverse('product-search') + '?q=Product', 5)

    def test_product_detail_limits_similar_products(self):
        extra = [Product.objects.create(name=f'Extra {i}', price=1, category=self.categories[0]) for i in range(10)]
        response = self.assertMaxQueries(reverse('product_detail', args=[extra[0].id]), 6)
        self.assertLessEqual(len(response.context['similar_products']), 8)
        self.assertNotIn(extra[0], list(response.context['similar_products']))

    def test_logged_in_home_with_cart(self):
        cart = Cart.objects.create(user=self.user)
        for p in self.products[:5]:
            CartItem.objects.create(cart=cart, product=p, quantity=2)
        self.client.force_login(self.user)
        response = self.assertMaxQueries(reverse('home'), 10)
        self.assertEqual(response.context['cart_count'], 10)
        self.assertEqual(response.context['cart_product_ids'], {p.id for p in self.products[:5]})

    def test_user_with_inactive_cart_stays_within_budget(self):
        # Only one active cart per user is possible now; an archived cart must not confuse lookups.
        Cart.objects.create(user=self.user, is_active=False)
        Cart.objects.create(user=self.user)
        self.client.force_login(self.user)
        self.assertMaxQueries(reverse('home'), 10)
        self.assertMaxQueries(reverse('product_detail', args=[self.products[0].id]), 11)

    def test_orders_page(self):
        for _ in range(3):
            order = Order.objects.create(user=self.user, paid=True)
            for p in self.products[:4]:
                OrderItem.objects.create(order=order, product=p, quantity=1, price=p.price)
        self.client.force_login(self.user)
        self.assertMaxQueries(reverse('orders'), 10)

    def test_session_cart_with_dict_values_is_robust(self):
        session = self.client.session
        session['cart'] = {
            self.products[0].id: 2,
            self.products[1].id: {'quantity': 3},
            self.products[2].id: 'junk',
        }
        session.save()
        n, response = self.count(reverse('home'))
        self.assertEqual(response.context['cart_count'], 5)
        self.assertEqual(len(response.context['cart_product_ids']), 3)

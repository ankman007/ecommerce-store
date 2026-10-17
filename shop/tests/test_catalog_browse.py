"""Catalog listing: pagination, sorting and price / stock filters on home, category and search."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from shop.models import Product
from shop.tests.helpers import make_category, make_product
from shop.views.listing import PRODUCTS_PER_PAGE


def names(response):
    return [p.name for p in response.context['products']]


class CatalogBrowseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tools = make_category('Tools')
        cls.toys = make_category('Toys')
        now = timezone.now()
        specs = [
            ('Anvil', '50.00', 3, cls.tools),
            ('Brush', '5.00', 0, cls.tools),
            ('Chisel', '12.50', 7, cls.tools),
            ('Doll', '20.00', 2, cls.toys),
            ('Easel', '35.00', 0, cls.toys),
        ]
        for age, (name, price, stock, category) in enumerate(specs):
            product = make_product(name=name, price=price, stock=stock, category=category)
            Product.objects.filter(pk=product.pk).update(created_at=now - timedelta(days=age))

    def get(self, url_name='home', args=None, **params):
        return self.client.get(reverse(url_name, args=args), params)

    def test_default_sort_is_newest(self):
        self.assertEqual(names(self.get()), ['Anvil', 'Brush', 'Chisel', 'Doll', 'Easel'])

    def test_sort_options(self):
        self.assertEqual(names(self.get(sort='price_asc')), ['Brush', 'Chisel', 'Doll', 'Easel', 'Anvil'])
        self.assertEqual(names(self.get(sort='price_desc')), ['Anvil', 'Easel', 'Doll', 'Chisel', 'Brush'])
        self.assertEqual(names(self.get(sort='name')), ['Anvil', 'Brush', 'Chisel', 'Doll', 'Easel'])

    def test_invalid_sort_falls_back_to_default(self):
        response = self.get(sort='DROP TABLE')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['filters']['sort'], 'newest')

    def test_price_range_filter(self):
        self.assertEqual(names(self.get(min_price='10', max_price='35', sort='price_asc')), ['Chisel', 'Doll', 'Easel'])
        self.assertEqual(names(self.get(min_price='20.00', sort='price_asc')), ['Doll', 'Easel', 'Anvil'])

    def test_invalid_price_is_ignored(self):
        response = self.get(min_price='cheap', max_price='-5')
        self.assertEqual(len(response.context['products']), 5)
        self.assertFalse(response.context['filters_active'])

    def test_in_stock_only(self):
        response = self.get(in_stock='1', sort='name')
        self.assertEqual(names(response), ['Anvil', 'Chisel', 'Doll'])
        self.assertContains(response, 'Clear filters')
        self.assertContains(response, 'noindex')

    def test_category_with_filters(self):
        response = self.get('category', args=[self.toys.slug], in_stock='on')
        self.assertEqual(names(response), ['Doll'])
        self.assertEqual(response.context['selected_category'], 'Toys')

    def test_search_with_sort_keeps_query(self):
        response = self.get('product-search', q='el', sort='price_desc')
        self.assertEqual(names(response), ['Easel', 'Chisel'])
        self.assertContains(response, 'name="q" value="el"')

    def test_empty_search_shows_nothing(self):
        response = self.get('product-search', q='  ')
        self.assertEqual(list(response.context['products']), [])

    def test_no_results_message_for_filters(self):
        response = self.get(min_price='1000')
        self.assertContains(response, 'No products match these filters')


class PaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = make_category('Bulk')
        for i in range(PRODUCTS_PER_PAGE * 2 + 3):
            make_product(name=f'Item {i:02d}', price=str(Decimal(i + 1)), stock=1, category=cls.category)

    def test_pages(self):
        response = self.client.get(reverse('home'), {'sort': 'price_asc'})
        self.assertEqual(len(response.context['products']), PRODUCTS_PER_PAGE)
        self.assertEqual(response.context['paginator'].num_pages, 3)
        self.assertTrue(response.context['is_paginated'])
        self.assertContains(response, f'1&ndash;{PRODUCTS_PER_PAGE} of {PRODUCTS_PER_PAGE * 2 + 3} products')
        # Links keep the other query parameters.
        self.assertContains(response, 'href="?sort=price_asc&amp;page=2"')

        response = self.client.get(reverse('home'), {'sort': 'price_asc', 'page': 3})
        self.assertEqual(names(response), ['Item 24', 'Item 25', 'Item 26'])
        self.assertContains(response, 'rel="prev"')

    def test_out_of_range_or_junk_page_is_handled(self):
        response = self.client.get(reverse('home'), {'page': 999})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].number, 3)
        response = self.client.get(reverse('home'), {'page': 'abc'})
        self.assertEqual(response.context['page_obj'].number, 1)

    def test_pages_do_not_overlap(self):
        seen = []
        for page in (1, 2, 3):
            seen += names(self.client.get(reverse('home'), {'page': page}))
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(len(seen), PRODUCTS_PER_PAGE * 2 + 3)

    def test_category_and_search_paginate(self):
        response = self.client.get(reverse('category', args=[self.category.slug]), {'page': 2})
        self.assertEqual(len(response.context['products']), PRODUCTS_PER_PAGE)
        response = self.client.get(reverse('product-search'), {'q': 'Item', 'page': 3})
        self.assertEqual(len(response.context['products']), 3)
        self.assertContains(response, 'q=Item&amp;page=2')

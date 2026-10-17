from django.test import TestCase
from django.urls import reverse

from shop.models import Product
from shop.tests.helpers import make_category, make_product


class CatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.electronics = make_category('Electronics')
        cls.books = make_category('Books')
        cls.phone = make_product('Smartphone X', price='299.99', category=cls.electronics,
                                 description='A great phone', with_image=True)
        cls.laptop = make_product('Laptop Pro', price='999.00', category=cls.electronics,
                                  description='Powerful laptop')
        cls.novel = make_product('Mystery Novel', price='15.00', category=cls.books,
                                 description='Thrilling read')

    def test_home_lists_all_products(self):
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        for p in (self.phone, self.laptop, self.novel):
            self.assertContains(resp, p.name)
        self.assertContains(resp, 'Electronics')

    def test_home_empty_catalog(self):
        Product.objects.all().delete()
        self.assertEqual(self.client.get(reverse('home')).status_code, 200)

    def test_category_filters_products(self):
        resp = self.client.get(reverse('category', args=[self.books.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Mystery Novel')
        self.assertNotContains(resp, 'Smartphone X')
        self.assertNotContains(resp, 'Laptop Pro')

    def test_unknown_category_404(self):
        self.assertEqual(self.client.get(reverse('category', args=['nope'])).status_code, 404)

    def test_search_by_name_case_insensitive(self):
        resp = self.client.get(reverse('product-search'), {'q': 'laptop'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Laptop Pro')
        self.assertNotContains(resp, 'Mystery Novel')

    def test_search_by_description(self):
        resp = self.client.get(reverse('product-search'), {'q': 'thrilling'})
        self.assertContains(resp, 'Mystery Novel')
        self.assertNotContains(resp, 'Laptop Pro')

    def test_search_no_results(self):
        resp = self.client.get(reverse('product-search'), {'q': 'zzzz-nothing'})
        self.assertEqual(resp.status_code, 200)
        for p in (self.phone, self.laptop, self.novel):
            self.assertNotContains(resp, p.name)

    def test_search_empty_query_returns_no_products(self):
        resp = self.client.get(reverse('product-search'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Mystery Novel')

    def test_product_detail_shows_product_and_similar(self):
        resp = self.client.get(reverse('product_detail', args=[self.phone.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Smartphone X')
        self.assertContains(resp, '299.99')
        self.assertContains(resp, 'Laptop Pro')  # similar product, same category
        self.assertNotContains(resp, 'Mystery Novel')

    def test_product_detail_without_image(self):
        resp = self.client.get(reverse('product_detail', args=[self.laptop.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Laptop Pro')

    def test_unknown_product_404(self):
        resp = self.client.get(reverse('product_detail', args=['doesnotexist']))
        self.assertEqual(resp.status_code, 404)

"""SEO: titles, meta description, canonical, Open Graph, sitemap.xml, robots.txt; image markup."""

import re

from django.test import TestCase
from django.urls import reverse

from shop.tests.helpers import make_category, make_product, make_user


class HeadTagTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = make_category('Kitchen')
        cls.product = make_product(
            name='Steel Pan',
            price='19.99',
            category=cls.category,
            description='<b>Heavy</b> steel pan',
            with_image=True,
        )
        cls.bare = make_product(name='Plain Box', price='3.00', description='')

    def test_home_head(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, '<title>A One Albany Wholesale')
        self.assertContains(response, '<meta name="description" content="Shop A One Albany Wholesale online')
        self.assertContains(response, '<link rel="canonical" href="http://testserver/" />')
        self.assertContains(response, 'property="og:site_name"')
        self.assertNotContains(response, 'noindex')

    def test_category_head(self):
        response = self.client.get(reverse('category', args=[self.category.slug]))
        self.assertContains(response, '<title>Kitchen | A One Albany Wholesale</title>')
        self.assertContains(response, 'content="Shop Kitchen at A One Albany Wholesale')
        self.assertContains(response, f'href="http://testserver/category/{self.category.slug}" />')

    def test_canonical_ignores_filters_but_keeps_page(self):
        response = self.client.get(reverse('home'), {'sort': 'name', 'utm_source': 'x'})
        self.assertContains(response, '<link rel="canonical" href="http://testserver/" />')

    def test_search_is_noindex(self):
        response = self.client.get(reverse('product-search'), {'q': 'pan'})
        self.assertContains(response, '<meta name="robots" content="noindex, follow">')
        self.assertContains(response, '<title>Search: pan | A One Albany Wholesale</title>')

    def test_product_head_and_open_graph(self):
        response = self.client.get(reverse('product_detail', args=[self.product.id]))
        html = response.content.decode()
        self.assertIn('<title>Steel Pan | Kitchen | A One Albany Wholesale</title>', html)
        self.assertIn('<meta name="description" content="Heavy steel pan" />', html)
        self.assertIn(f'<link rel="canonical" href="http://testserver/product/{self.product.id}" />', html)
        self.assertIn('<meta property="og:type" content="product" />', html)
        self.assertIn('<meta property="og:title" content="Steel Pan" />', html)
        self.assertIn('<meta property="product:price:amount" content="19.99" />', html)
        og_image = re.search(r'<meta property="og:image" content="([^"]+)"', html).group(1)
        self.assertTrue(og_image.startswith('http://testserver/'), og_image)
        self.assertNotIn('<b>', re.search(r'<meta property="og:description" content="([^"]*)"', html).group(1))

    def test_product_without_image_or_description(self):
        response = self.client.get(reverse('product_detail', args=[self.bare.id]))
        self.assertContains(response, 'content="Buy Plain Box for $3.00 at A One Albany Wholesale." />')
        self.assertNotContains(response, 'og:image"')
        self.assertContains(response, 'No image available')

    def test_title_is_escaped(self):
        evil = make_product(name='<script>x</script> Pan', price='1.00')
        response = self.client.get(reverse('product_detail', args=[evil.id]))
        self.assertNotContains(response, '<title><script>')
        self.assertContains(response, '&lt;script&gt;x&lt;/script&gt; Pan')

    def test_private_pages_are_noindex(self):
        self.assertContains(self.client.get(reverse('cart')), 'noindex, nofollow')

    def test_product_images_markup(self):
        response = self.client.get(reverse('home'))
        html = response.content.decode()
        card_img = re.search(
            r'<img src="[^"]+" alt="([^"]*)" loading="lazy" decoding="async" width="600" height="600">', html
        )
        self.assertIsNotNone(card_img)
        # The auto-generated slug alt text ("steel-pan") is replaced by the product name.
        self.assertEqual(card_img.group(1), 'Steel Pan')
        self.assertContains(response, 'aria-label="No image available for Plain Box"')

    def test_product_detail_main_image_not_lazy(self):
        html = self.client.get(reverse('product_detail', args=[self.product.id])).content.decode()
        main = re.search(r'<img\s+id="main-product-image"[^>]*>', html).group(0)
        self.assertIn('fetchpriority="high"', main)
        self.assertNotIn('loading="lazy"', main)
        self.assertIn('alt="Steel Pan"', main)


class SitemapRobotsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = make_category('Garden')
        cls.product = make_product(name='Hose', category=cls.category)

    def test_sitemap(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/xml')
        body = response.content.decode()
        self.assertIn(f'<loc>http://testserver/product/{self.product.id}</loc>', body)
        self.assertIn(f'<loc>http://testserver/category/{self.category.slug}</loc>', body)
        self.assertIn('<loc>http://testserver/</loc>', body)
        self.assertIn('<loc>http://testserver/about/</loc>', body)
        self.assertIn('<lastmod>', body)
        self.assertNotIn('/cart/', body)
        self.assertNotIn('example.com', body)

    def test_sitemap_uses_request_host(self):
        with self.settings(ALLOWED_HOSTS=['shop.example.org']):
            response = self.client.get('/sitemap.xml', HTTP_HOST='shop.example.org')
        self.assertIn(f'http://shop.example.org/product/{self.product.id}', response.content.decode())

    def test_robots_txt(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('text/plain'))
        body = response.content.decode()
        self.assertTrue(body.startswith('User-agent: *'))
        for path in ('/cart/', '/checkout/', '/accounts/', '/admin/', '/orders/'):
            self.assertIn(f'Disallow: {path}\n', body)
        self.assertIn('Sitemap: http://testserver/sitemap.xml', body)
        self.assertNotIn('Disallow: /\n', body)

    def test_robots_rejects_post(self):
        self.assertEqual(self.client.post('/robots.txt').status_code, 405)


class LoggedInHeadTests(TestCase):
    def test_checkout_page_title(self):
        user = make_user('erin')
        self.client.force_login(user)
        product = make_product()
        from shop.models import Cart

        Cart.objects.create(user=user).items.create(product=product, quantity=1)
        response = self.client.get(reverse('checkout_address'))
        self.assertContains(response, '<title>Checkout | A One Albany Wholesale</title>')

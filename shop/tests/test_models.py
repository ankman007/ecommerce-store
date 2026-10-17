import importlib
from decimal import Decimal

from django.apps import apps as django_apps
from django.test import TestCase
from PIL import Image

from shop.models import Cart, CartItem, Category, Product, ProductImage, generate_product_id
from shop.tests.helpers import make_category, make_image_file, make_product, make_user


class CategoryModelTests(TestCase):
    def test_slug_auto_generated_from_name(self):
        cat = Category.objects.create(name='Home Appliances & More')
        self.assertEqual(cat.slug, 'home-appliances-more')

    def test_explicit_slug_is_kept(self):
        cat = Category.objects.create(name='Books', slug='my-books')
        self.assertEqual(cat.slug, 'my-books')

    def test_slug_not_regenerated_on_rename(self):
        cat = Category.objects.create(name='Toys')
        cat.name = 'Games'
        cat.save()
        cat.refresh_from_db()
        self.assertEqual(cat.slug, 'toys')


class ProductModelTests(TestCase):
    def test_generate_product_id_length_and_uniqueness(self):
        ids = {generate_product_id() for _ in range(500)}
        self.assertEqual(len(ids), 500)
        self.assertTrue(all(len(i) == 8 for i in ids))

    def test_products_get_distinct_ids(self):
        p1 = make_product('A')
        p2 = make_product('B')
        self.assertEqual(len(p1.id), 8)
        self.assertNotEqual(p1.id, p2.id)
        self.assertEqual(Product.objects.count(), 2)

    def test_description_plain_text_normalised(self):
        # Descriptions are plain text now (CKEditor removed): save() trims surrounding
        # whitespace and normalises Windows/old-Mac newlines, and keeps everything else.
        p = make_product(description='  First line\r\nSecond line\rThird\n\n')
        self.assertEqual(p.description, 'First line\nSecond line\nThird')
        p.refresh_from_db()
        self.assertEqual(p.description, 'First line\nSecond line\nThird')

    def test_description_text_kept_verbatim(self):
        p = make_product(description='Size < 5 & AT&T <b>not markup</b>')
        self.assertEqual(p.description, 'Size < 5 & AT&T <b>not markup</b>')

    def test_description_rendered_escaped_with_line_breaks(self):
        p = make_product(description='Line one\nLine <b>two</b>')
        response = self.client.get(p.get_absolute_url())
        self.assertContains(response, 'Line one<br>Line &lt;b&gt;two&lt;/b&gt;')
        self.assertNotContains(response, 'Line <b>two</b>')


class DescriptionDataMigrationTests(TestCase):
    """0007 converts HTML saved by CKEditor into plain text."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        module = importlib.import_module('shop.migrations.0007_product_description_plain_text')
        cls.convert = staticmethod(module.html_to_plain_text)

    def test_paragraphs_become_blank_line_separated(self):
        self.assertEqual(self.convert('<p>Hello&nbsp;world</p>\r\n\r\n<p>Second</p>'), 'Hello world\n\nSecond')

    def test_br_and_inline_tags(self):
        self.assertEqual(self.convert('<p><strong>Bold</strong> text<br />\r\nnext line</p>'), 'Bold text\nnext line')

    def test_entities_unescaped(self):
        self.assertEqual(self.convert('Fish &amp; chips &lt;3 &quot;hot&quot;'), 'Fish & chips <3 "hot"')

    def test_rows_saved_by_old_save(self):
        # The old save() replaced <p>/</p>/&nbsp; with spaces; newlines carry the paragraphs.
        self.assertEqual(self.convert(' One <em>a</em> \r\n\r\n Two '), 'One a\n\nTwo')

    def test_lists_and_excess_blank_lines(self):
        value = '<ul>\n\t<li>Red</li>\n\t<li>Blue</li>\n</ul>\n\n\n\n<p>End</p>'
        self.assertEqual(self.convert(value), 'Red\nBlue\n\nEnd')

    def test_plain_text_left_alone(self):
        self.assertEqual(self.convert('  AT&T, size < 5\n\n\nok  '), 'AT&T, size < 5\n\n\nok')
        self.assertEqual(self.convert(''), '')
        self.assertEqual(self.convert(None), '')

    def test_migration_rewrites_existing_rows(self):
        module = importlib.import_module('shop.migrations.0007_product_description_plain_text')
        html_product = make_product(name='Html', description='x')
        plain_product = make_product(name='Plain', description='Already plain')
        Product.objects.filter(pk=html_product.pk).update(description='<p>A&nbsp;<b>B</b></p>\n<p>C</p>')
        module.convert_descriptions(django_apps, None)
        html_product.refresh_from_db()
        plain_product.refresh_from_db()
        self.assertEqual(html_product.description, 'A B\n\nC')
        self.assertEqual(plain_product.description, 'Already plain')

    def test_str_without_category(self):
        self.assertIn('Uncategorized', str(make_product('Lonely')))

    def test_category_set_null_on_delete(self):
        cat = make_category()
        p = make_product(category=cat)
        cat.delete()
        p.refresh_from_db()
        self.assertIsNone(p.category)


class ProductImageModelTests(TestCase):
    def test_image_converted_to_jpeg_resized_and_alt_text_defaulted(self):
        p = make_product('Shiny Thing')
        img = ProductImage.objects.create(product=p, images=make_image_file(size=(2000, 1000)))
        self.assertEqual(img.alt_text, 'shiny-thing')
        img.images.open()
        opened = Image.open(img.images)
        self.assertEqual(opened.format, 'JPEG')
        self.assertLessEqual(max(opened.size), 1200)


class CartItemModelTests(TestCase):
    def test_subtotal(self):
        cart = Cart.objects.create(user=make_user())
        item = CartItem.objects.create(cart=cart, product=make_product(price='12.50'), quantity=3)
        self.assertEqual(item.subtotal(), Decimal('37.50'))

    def test_default_quantity_is_one(self):
        cart = Cart.objects.create(user=make_user())
        item = CartItem.objects.create(cart=cart, product=make_product(price='4.00'))
        self.assertEqual(item.quantity, 1)
        self.assertEqual(item.subtotal(), Decimal('4.00'))

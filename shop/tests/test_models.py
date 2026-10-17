from decimal import Decimal

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

    def test_description_html_paragraphs_stripped(self):
        p = make_product(description='<p>Hello&nbsp;world</p>')
        self.assertNotIn('<p>', p.description)
        self.assertNotIn('&nbsp;', p.description)
        self.assertIn('Hello', p.description)

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

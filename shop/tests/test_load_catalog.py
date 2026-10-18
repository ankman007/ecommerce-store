import json
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from shop.models import Category, Product

from .helpers import make_image_file


class LoadCatalogTests(TestCase):
    def write_catalog(self, products, with_images=True):
        tmp = Path(tempfile.mkdtemp())
        (tmp / 'images').mkdir()
        if with_images:
            for entry in products:
                (tmp / 'images' / entry['image']).write_bytes(make_image_file().read())
        path = tmp / 'products.json'
        path.write_text(json.dumps({'products': products}), encoding='utf-8')
        return str(path)

    def entry(self, **changes):
        base = {
            'name': 'Test Cream',
            'category': 'Skincare',
            'price': '9.99',
            'stock': 5,
            'image': 'test-cream.jpg',
            'description': 'Line one.\n\nLine two.',
        }
        return {**base, **changes}

    def load(self, *args):
        out = StringIO()
        call_command('load_catalog', *args, stdout=out)
        return out.getvalue()

    def test_creates_products_with_category_and_image(self):
        path = self.write_catalog([self.entry()])
        output = self.load('--file', path)
        product = Product.objects.get(name='Test Cream')
        self.assertEqual(product.category.name, 'Skincare')
        self.assertEqual(product.price, Decimal('9.99'))
        self.assertEqual(product.stock, 5)
        self.assertEqual(product.images.count(), 1)
        self.assertEqual(product.images.get().alt_text, 'Test Cream')
        self.assertIn('1 created', output)

    def test_rerunning_does_not_duplicate(self):
        path = self.write_catalog([self.entry()])
        self.load('--file', path)
        output = self.load('--file', path)
        self.assertEqual(Product.objects.filter(name='Test Cream').count(), 1)
        self.assertEqual(Product.objects.get(name='Test Cream').images.count(), 1)
        self.assertEqual(Category.objects.filter(name='Skincare').count(), 1)
        self.assertIn('1 already present', output)

    def test_update_changes_details_but_never_stock(self):
        self.load('--file', self.write_catalog([self.entry()]))
        Product.objects.filter(name='Test Cream').update(stock=2)  # some were sold
        self.load('--file', self.write_catalog([self.entry(price='12.00', stock=50)]), '--update')
        product = Product.objects.get(name='Test Cream')
        self.assertEqual(product.price, Decimal('12.00'))
        self.assertEqual(product.stock, 2)

    def test_missing_image_fails_before_writing_anything(self):
        path = self.write_catalog([self.entry()], with_images=False)
        with self.assertRaisesMessage(CommandError, 'test-cream.jpg'):
            self.load('--file', path)
        self.assertFalse(Product.objects.exists())

    def test_bundled_catalog_is_valid(self):
        # The real catalog/products.json and catalog/images/ shipped in the repo and Docker image.
        self.load()
        names = set(Product.objects.values_list('name', flat=True))
        self.assertIn('Dior Sauvage', names)
        self.assertEqual(len(names), 11)
        self.assertFalse(Product.objects.filter(images__isnull=True).exists())

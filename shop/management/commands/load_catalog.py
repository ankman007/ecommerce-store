import json
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from shop.models import Category, Product, ProductImage

DEFAULT_CATALOG = Path(settings.BASE_DIR) / 'catalog' / 'products.json'


class Command(BaseCommand):
    help = "Load the store catalog (catalog/products.json + catalog/images/) into the database. Safe to re-run."

    def add_arguments(self, parser):
        parser.add_argument('--file', default=str(DEFAULT_CATALOG), help='Path to the catalog JSON file.')
        parser.add_argument(
            '--update',
            action='store_true',
            help='Also update name-matched products that already exist (category, price, description). '
            'Stock is never overwritten, so sales are not undone.',
        )

    def handle(self, *args, **options):
        path = Path(options['file'])
        if not path.is_file():
            raise CommandError(f"Catalog file not found: {path}")
        entries = json.loads(path.read_text(encoding='utf-8')).get('products', [])
        image_dir = path.parent / 'images'

        missing = [e['image'] for e in entries if e.get('image') and not (image_dir / e['image']).is_file()]
        if missing:
            raise CommandError(f"Missing image files in {image_dir}: {', '.join(missing)}")

        created = updated = skipped = 0
        with transaction.atomic():
            for entry in entries:
                category, _ = Category.objects.get_or_create(name=entry['category'])
                product = Product.objects.filter(name=entry['name']).first()

                if product is None:
                    product = Product.objects.create(
                        name=entry['name'],
                        category=category,
                        price=Decimal(entry['price']),
                        stock=entry.get('stock', 0),
                        description=entry.get('description', ''),
                    )
                    created += 1
                elif options['update']:
                    product.category = category
                    product.price = Decimal(entry['price'])
                    product.description = entry.get('description', '')
                    product.save()
                    updated += 1
                else:
                    skipped += 1

                if entry.get('image') and not product.images.exists():
                    with open(image_dir / entry['image'], 'rb') as fh:
                        # ProductImage.save() resizes and re-encodes the upload as JPEG.
                        ProductImage.objects.create(
                            product=product, images=File(fh, name=entry['image']), alt_text=entry['name']
                        )

        self.stdout.write(
            self.style.SUCCESS(f"Catalog loaded: {created} created, {updated} updated, {skipped} already present.")
        )

"""Shared factories for shop/users tests."""

from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from shop.models import Category, Product, ProductImage

PASSWORD = 'S3cure-pass!'


def make_image_file(name='test.png', size=(10, 10), color=(255, 0, 0)):
    buf = BytesIO()
    Image.new('RGB', size, color).save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


def make_user(username='alice', email=None, password=PASSWORD):
    return User.objects.create_user(username=username, email=email or f'{username}@example.com', password=password)


def make_category(name='Electronics'):
    return Category.objects.create(name=name)


def make_product(name='Widget', price='10.00', stock=10, category=None, description='A fine product', with_image=False):
    product = Product.objects.create(
        name=name,
        price=Decimal(price),
        stock=stock,
        category=category,
        description=description,
    )
    if with_image:
        ProductImage.objects.create(product=product, images=make_image_file())
    return product

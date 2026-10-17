from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
from decimal import Decimal
from ckeditor.fields import RichTextField
from PIL import Image
from io import BytesIO
import re
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone
import shortuuid


def generate_product_id():
    return shortuuid.ShortUUID().random(length=8)


class Category(models.Model):
    name = models.CharField(unique=True, max_length=200)
    slug = models.SlugField(unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('category', args=[self.slug])

    def __str__(self):
        return f"Category: {self.name}"


class Product(models.Model):
    id = models.CharField(primary_key=True, max_length=22, unique=True, default=generate_product_id, editable=False)
    name = models.CharField(max_length=200)
    description = RichTextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='products')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    stock = models.PositiveIntegerField(default=0)

    def get_absolute_url(self):
        return reverse('product_detail', args=[self.id])

    def save(self, *args, **kwargs):
        self.description = re.sub(r'&nbsp;|<p>|</p>', ' ', self.description).strip()
        super().save(*args, **kwargs)

    def __str__(self):
        category_name = self.category.name if self.category else "Uncategorized"
        return f"Product: {self.name} (Category: {category_name})"

    class Meta:
        ordering = ['-id']


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    images = models.ImageField(upload_to='product_images/')
    alt_text = models.CharField(max_length=255, blank=True)

    def save(self, *args, **kwargs):
        if not self.alt_text:
            self.alt_text = slugify(self.product.name)

        if self.images and not self.pk or self.has_changed_image():
            img = Image.open(self.images)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            max_size = (1200, 1200)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            output = BytesIO()
            img.save(output, format='JPEG', quality=75)
            output.seek(0)
            self.images = ContentFile(output.read(), self.images.name)
        super().save(*args, **kwargs)

    @property
    def alt(self):
        """Alt text for templates: the product name instead of the auto-generated slug."""
        if self.alt_text and self.alt_text != slugify(self.product.name):
            return self.alt_text
        return self.product.name

    def has_changed_image(self):
        """Check if image was updated to avoid double compression"""
        if not self.pk:
            return True
        old = ProductImage.objects.get(pk=self.pk)
        return old.images != self.images


class Cart(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="carts")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            # One active cart per user; stops concurrent requests creating duplicates.
            # (MySQL can't enforce conditional unique constraints, hence (user, is_active).
            # Nothing deactivates carts today; archiving more than one per user would need
            # deleting old inactive carts first.)
            models.UniqueConstraint(fields=['user', 'is_active'], name='unique_cart_per_user_state'),
        ]

    def __str__(self):
        return f"Cart for {self.user.username} - Created at {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='cart_product')
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['cart', 'product'], name='unique_product_per_cart'),
        ]

    def subtotal(self):
        return self.quantity * Decimal(self.product.price)

    def __str__(self):
        return f"{self.quantity} x {self.product.name} (Subtotal: ${self.subtotal():.2f})"


class Payment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('shipped', 'Shipped'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, default='pending', choices=STATUS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payment by {self.user.username} | ₹{self.total_price} | Status: {self.get_status_display()}"


class Order(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PAID = 'paid'
    STATUS_SHIPPED = 'shipped'
    STATUS_CANCELLED = 'cancelled'
    STATUS_NEEDS_REVIEW = 'needs_review'
    STATUS_REFUNDED = 'refunded'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PAID, 'Paid'),
        (STATUS_NEEDS_REVIEW, 'Paid - needs review'),
        (STATUS_SHIPPED, 'Shipped'),
        (STATUS_REFUNDED, 'Refunded'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    stripe_session_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    stripe_payment_intent = models.CharField(max_length=255, blank=True, null=True)
    # `paid` is kept for backwards compatibility; `status` is the richer source of truth.
    paid = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    paid_at = models.DateTimeField(null=True, blank=True)

    # Shipping snapshot taken at checkout, so later profile/address changes never alter past orders.
    full_name = models.CharField(max_length=120, blank=True, default='')
    phone = models.CharField(max_length=30, blank=True, default='')
    address_line1 = models.CharField('address line 1', max_length=200, blank=True, default='')
    address_line2 = models.CharField('address line 2', max_length=200, blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    state = models.CharField('state / region', max_length=100, blank=True, default='')
    postal_code = models.CharField(max_length=20, blank=True, default='')
    country = models.CharField(max_length=2, blank=True, default='', help_text='ISO 3166-1 alpha-2 code')

    shipped_at = models.DateTimeField(null=True, blank=True)
    tracking_number = models.CharField(max_length=100, blank=True, default='')
    # Set when the confirmation email is handed to the mailer; guards against double sends.
    confirmation_sent_at = models.DateTimeField(null=True, blank=True, editable=False)

    ADDRESS_FIELDS = ('full_name', 'phone', 'address_line1', 'address_line2', 'city', 'state', 'postal_code', 'country')

    class Meta:
        indexes = [
            models.Index(fields=['user', '-created_at'], name='order_user_created_idx'),
            models.Index(fields=['status', 'created_at'], name='order_status_created_idx'),
        ]

    def __str__(self):
        return f"Order #{self.id} by {self.user}"

    @property
    def has_shipping_address(self):
        return bool(self.address_line1)

    @property
    def country_name(self):
        from shop.forms import COUNTRY_NAMES

        return COUNTRY_NAMES.get(self.country, self.country)

    def shipping_address_lines(self):
        """The snapshot address as display lines (empty list if none was collected)."""
        if not self.has_shipping_address:
            return []
        region = ' '.join(part for part in (self.state, self.postal_code) if part)
        city_line = ', '.join(part for part in (self.city, region) if part)
        lines = [self.full_name, self.address_line1, self.address_line2, city_line, self.country_name]
        return [line for line in lines if line]

    @property
    def subtotal(self):
        return self.total - self.shipping_cost


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)  # price at the time of order

    def subtotal(self):
        return self.quantity * self.price

    def __str__(self):
        name = self.product.name if self.product else "Deleted product"
        return f"{self.quantity} x {name}"

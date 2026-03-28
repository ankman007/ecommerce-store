from django.db import models
from django.contrib.auth.models import User
from django.utils.text import slugify
from decimal import Decimal
from ckeditor.fields import RichTextField
from PIL import Image
from io import BytesIO
import re
from django.core.files.base import ContentFile
import shortuuid

class Category(models.Model):
    name = models.CharField(unique=True, max_length=200)
    slug = models.SlugField(unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Category: {self.name}"


class Product(models.Model):
    id = models.CharField(
        primary_key=True,
        max_length=22,
        unique=True,
        default=shortuuid.ShortUUID().random(length=8),
        editable=False
    )
    name = models.CharField(max_length=200)
    description = RichTextField(blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        related_name='products'
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    updated_at = models.DateTimeField(auto_now=True)
    stock = models.PositiveIntegerField(default=0)
    
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

    def __str__(self):
        return f"Cart for {self.user.username} - Created at {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='cart_product')
    quantity = models.PositiveIntegerField(default=1) 
    
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
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    stripe_session_id = models.CharField(max_length=255, blank=True, null=True)
    paid = models.BooleanField(default=False)

    def __str__(self):
        return f"Order #{self.id} by {self.user}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)  # price at the time of order

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

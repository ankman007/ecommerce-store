from django.contrib import admin
from django import forms
from ckeditor.widgets import CKEditorWidget
from .models import (
    Product,
    ProductImage,
    Cart,
    CartItem,
    Category,
    Payment,
)

class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = '__all__'
        widgets = {
            'description': CKEditorWidget(),
        }

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = ('name', 'category', 'price', 'stock', 'updated_at')
    search_fields = ('name', 'category__name')
    list_filter = ('category',)
    readonly_fields = ('id',)

@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ('product', 'alt_text')
    search_fields = ('product__name',)

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}

class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ('subtotal',)

@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at', 'updated_at', 'is_active')
    list_filter = ('created_at', 'is_active')
    inlines = [CartItemInline]

@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('cart', 'product', 'quantity', 'subtotal')
    readonly_fields = ('subtotal',)
    search_fields = ('product__name',)

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('user', 'total_price', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username',)

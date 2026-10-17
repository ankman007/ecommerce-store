import stripe
from django.contrib import admin, messages
from django import forms
from ckeditor.widgets import CKEditorWidget
from .models import (
    Product,
    ProductImage,
    Cart,
    CartItem,
    Category,
    Payment,
    Order,
    OrderItem,
)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ('images', 'alt_text')


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
    list_select_related = ('category',)
    inlines = [ProductImageInline]


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ('product', 'alt_text')
    search_fields = ('product__name',)
    list_select_related = ('product',)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    raw_id_fields = ('product',)
    readonly_fields = ('subtotal',)


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at', 'updated_at', 'is_active')
    list_filter = ('created_at', 'is_active')
    search_fields = ('user__username', 'user__email')
    list_select_related = ('user',)
    inlines = [CartItemInline]


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('cart', 'product', 'quantity', 'subtotal')
    readonly_fields = ('subtotal',)
    search_fields = ('product__name',)
    list_select_related = ('cart__user', 'product')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('user', 'total_price', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'user__email')
    list_select_related = ('user',)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    fields = ('product', 'quantity', 'price', 'line_total')
    readonly_fields = fields

    @admin.display(description='Line total')
    def line_total(self, obj):
        if obj.price is None or obj.quantity is None:
            return '-'
        return obj.price * obj.quantity

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('product')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'created_at', 'status', 'total', 'paid_at')
    list_filter = ('status', 'paid', 'created_at')
    search_fields = ('id', 'user__username', 'user__email', 'stripe_session_id', 'stripe_payment_intent')
    list_select_related = ('user',)
    readonly_fields = ('created_at', 'paid_at', 'total', 'shipping_cost', 'stripe_session_id', 'stripe_payment_intent')
    raw_id_fields = ('user',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    inlines = [OrderItemInline]
    actions = ['refund_via_stripe', 'mark_reviewed']

    @admin.action(description='Refund via Stripe (full amount)')
    def refund_via_stripe(self, request, queryset):
        from shop.views.payment import refund_order

        refunded = 0
        for order in queryset:
            try:
                refund_order(order)
                refunded += 1
            except ValueError as exc:
                self.message_user(request, f"Order #{order.pk} not refunded: {exc}.", messages.WARNING)
            except stripe.StripeError as exc:
                self.message_user(
                    request,
                    f"Order #{order.pk}: Stripe refused the refund ({exc.user_message or exc}).",
                    messages.ERROR,
                )
        if refunded:
            self.message_user(
                request,
                f"Refunded {refunded} order(s). Stock was not restored; adjust it on the products if needed.",
                messages.SUCCESS,
            )

    @admin.action(description='Mark reviewed (keep as paid)')
    def mark_reviewed(self, request, queryset):
        updated = queryset.filter(status=Order.STATUS_NEEDS_REVIEW, paid=True).update(status=Order.STATUS_PAID)
        self.message_user(request, f"{updated} order(s) marked as reviewed.", messages.SUCCESS)

from functools import partial

import stripe
from django.contrib import admin, messages
from django import forms
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
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
            'description': forms.Textarea(attrs={'rows': 8}),
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
    list_display = ('id', 'customer', 'created_at', 'status', 'total', 'paid_at', 'shipped_at')
    list_filter = ('status', 'paid', 'created_at', 'shipped_at')
    search_fields = (
        'id',
        'user__username',
        'user__email',
        'full_name',
        'phone',
        'postal_code',
        'tracking_number',
        'stripe_session_id',
        'stripe_payment_intent',
    )
    list_select_related = ('user',)
    readonly_fields = (
        'created_at',
        'paid_at',
        'shipped_at',
        'customer_link',
        'subtotal_display',
        'total',
        'shipping_cost',
        'shipping_address',
        'phone',
        'stripe_session_id',
        'stripe_payment_intent',
        'confirmation_sent_at',
    )
    fieldsets = (
        (None, {'fields': ('user', 'customer_link', 'status', 'paid', 'created_at', 'paid_at')}),
        ('Fulfilment', {'fields': ('shipping_address', 'phone', 'tracking_number', 'shipped_at')}),
        ('Totals', {'fields': ('subtotal_display', 'shipping_cost', 'total')}),
        (
            'Payment',
            {
                'classes': ('collapse',),
                'fields': ('stripe_session_id', 'stripe_payment_intent', 'confirmation_sent_at'),
            },
        ),
    )
    raw_id_fields = ('user',)
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    inlines = [OrderItemInline]
    actions = ['mark_shipped', 'refund_via_stripe', 'mark_reviewed']

    @admin.display(description='Customer', ordering='user__username')
    def customer(self, obj):
        if obj.user is None:
            return obj.full_name or '-'
        return obj.user.get_full_name() or obj.user.username

    @admin.display(description='Customer account')
    def customer_link(self, obj):
        if obj.user_id is None:
            return '-'
        url = reverse('admin:auth_user_change', args=[obj.user_id])
        return format_html('<a href="{}">{}</a> ({})', url, obj.user.username, obj.user.email or 'no email')

    @admin.display(description='Subtotal')
    def subtotal_display(self, obj):
        return obj.subtotal

    @admin.display(description='Shipping address')
    def shipping_address(self, obj):
        lines = obj.shipping_address_lines()
        if not lines:
            return 'No address collected'
        return format_html_join(mark_safe('<br>'), '{}', ((line,) for line in lines))

    def save_model(self, request, obj, form, change):
        # Setting the status to "Shipped" by hand behaves like the "Mark as shipped" action.
        newly_shipped = (
            change and 'status' in form.changed_data and obj.status == Order.STATUS_SHIPPED and not obj.shipped_at
        )
        if newly_shipped:
            obj.shipped_at = timezone.now()
        super().save_model(request, obj, form, change)
        if newly_shipped:
            from shop.tasks import send_order_status_email

            transaction.on_commit(partial(send_order_status_email.delay, obj.pk, 'shipped'))

    @admin.action(description='Mark as shipped (emails the customer)')
    def mark_shipped(self, request, queryset):
        from shop.views.order import mark_order_shipped

        shipped = 0
        for order in queryset:
            try:
                mark_order_shipped(order)
                shipped += 1
            except ValueError as exc:
                self.message_user(request, f"Order #{order.pk} not shipped: {exc}.", messages.WARNING)
        if shipped:
            self.message_user(
                request,
                f"Marked {shipped} order(s) as shipped. Add tracking numbers on each order before shipping "
                "if you want them in the email.",
                messages.SUCCESS,
            )

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

from functools import partial

from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from shop.models import Order, OrderItem, ProductImage

SHIPPABLE_STATUSES = (Order.STATUS_PAID,)


def mark_order_shipped(order, tracking_number=None):
    """Mark a paid order as shipped (optionally with a tracking number) and email the customer.

    Raises ValueError if the order isn't paid (needs-review orders must be reviewed first).
    """
    from shop.tasks import send_order_status_email

    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.status not in SHIPPABLE_STATUSES or not locked.paid:
            raise ValueError(f"order is {locked.get_status_display().lower()}")
        locked.status = Order.STATUS_SHIPPED
        locked.shipped_at = timezone.now()
        fields = ['status', 'shipped_at']
        if tracking_number is not None:
            locked.tracking_number = tracking_number.strip()
            fields.append('tracking_number')
        locked.save(update_fields=fields)
        transaction.on_commit(partial(send_order_status_email.delay, locked.pk, 'shipped'))
    for field in fields:
        setattr(order, field, getattr(locked, field))
    return order


def _paid_orders_for(user):
    # Pending/cancelled checkouts are not real orders for the customer
    return Order.objects.filter(user=user, paid=True).prefetch_related(
        Prefetch('items', queryset=OrderItem.objects.select_related('product').order_by('id')),
        Prefetch('items__product__images', queryset=ProductImage.objects.order_by('id')),
    )


@login_required
def order(request):
    orders = _paid_orders_for(request.user).order_by('-created_at')
    return render(
        request,
        'a_shop/order.html',
        {
            'orders': orders,
        },
    )


@login_required
def order_detail(request, order_id):
    # Scoped to the current user, so other customers' order ids return 404
    order = get_object_or_404(_paid_orders_for(request.user), pk=order_id)
    return render(
        request,
        'a_shop/order_detail.html',
        {
            'order': order,
            'just_placed': request.GET.get('placed') == '1',
        },
    )

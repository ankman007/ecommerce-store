from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from shop.models import Order, OrderItem, ProductImage


def _paid_orders_for(user):
    # Pending/cancelled checkouts are not real orders for the customer
    return Order.objects.filter(user=user, paid=True).prefetch_related(
        Prefetch('items', queryset=OrderItem.objects.select_related('product').order_by('id')),
        Prefetch('items__product__images', queryset=ProductImage.objects.order_by('id')),
    )


@login_required
def order(request):
    orders = _paid_orders_for(request.user).order_by('-created_at')
    return render(request, 'a_shop/order.html', {
        'orders': orders,
    })


@login_required
def order_detail(request, order_id):
    # Scoped to the current user, so other customers' order ids return 404
    order = get_object_or_404(_paid_orders_for(request.user), pk=order_id)
    return render(request, 'a_shop/order_detail.html', {
        'order': order,
        'just_placed': request.GET.get('placed') == '1',
    })

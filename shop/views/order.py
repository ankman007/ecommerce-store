from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from shop.models import Order

@login_required
def order(request):
    orders = Order.objects.filter(user=request.user).prefetch_related('items__product').order_by('-created_at')
    
    return render(request, 'a_shop/order.html', {
        'orders': orders,
    })

from django.db.models import Sum
from django.utils import timezone

from .models import Category, CartItem
from .utils import get_request_cart


def _session_quantity(value):
    """Session cart values are normally ints, but tolerate dicts ({'quantity': n}) and junk."""
    if isinstance(value, dict):
        value = value.get('quantity', 0)
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def cart_count(request):
    count = 0
    if request.user.is_authenticated:
        cart = get_request_cart(request)
        if cart:
            count = CartItem.objects.filter(cart=cart).aggregate(total=Sum('quantity'))['total'] or 0
    else:
        session_cart = request.session.get('cart', {})
        if isinstance(session_cart, dict):
            count = sum(_session_quantity(v) for v in session_cart.values())
    return {'cart_count': count}


def site_context(request):
    """Data the shared header/footer need on every page."""
    return {
        'footer_categories': Category.objects.order_by('name')[:6],
        'year': timezone.now().year,
    }

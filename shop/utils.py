from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from shop.models import Cart, CartItem, Product, ProductImage


def product_grid_queryset(queryset=None):
    """Product queryset for card grids: category joined, images prefetched (2 queries total)."""
    if queryset is None:
        queryset = Product.objects.all()
    return queryset.select_related('category').prefetch_related(
        Prefetch('images', queryset=ProductImage.objects.order_by('id'))
    )


def get_user_cart(user, create=False):
    """Return the user's active cart (or None). Cart.user is a ForeignKey, so never use .get()."""
    cart = Cart.objects.filter(user=user, is_active=True).order_by('-updated_at').first()
    if cart is None and create:
        try:
            with transaction.atomic():
                cart = Cart.objects.create(user=user)
        except IntegrityError:
            # A concurrent request created it first (unique_cart_per_user_state).
            cart = Cart.objects.filter(user=user, is_active=True).first()
    return cart


def change_cart_line(cart, product, quantity=None, add=0):
    """Atomically set (``quantity``) or increase (``add``) a cart line, capped by stock.

    The line is locked while it is read and written, so concurrent add-to-cart clicks
    cannot overwrite each other. A resulting quantity of 0 removes the line.
    Returns ``(previous_quantity, new_quantity)``.
    """
    with transaction.atomic():
        CartItem.objects.get_or_create(cart=cart, product=product, defaults={'quantity': 0})
        item = CartItem.objects.select_for_update().get(cart=cart, product=product)
        previous = item.quantity
        target = previous + add if quantity is None else quantity
        new = max(0, min(target, product.stock))
        if new == 0:
            item.delete()
        elif new != previous:
            item.quantity = new
            item.save(update_fields=['quantity'])
    return previous, new


_MISSING = object()


def get_request_cart(request):
    """Per-request cached cart lookup (shared by views and the cart_count context processor)."""
    cached = getattr(request, '_shop_cart_cache', _MISSING)
    if cached is _MISSING:
        cached = get_user_cart(request.user) if request.user.is_authenticated else None
        request._shop_cart_cache = cached
    return cached


def check_product_for_cart(request):
    """Return the set of product ids currently in the visitor's cart."""
    if request.user.is_authenticated:
        cart = get_request_cart(request)
        if cart is None:
            return set()
        return set(cart.items.values_list('product_id', flat=True))
    session_cart = request.session.get('cart', {})
    if not isinstance(session_cart, dict):
        return set()
    return set(str(pid) for pid in session_cart.keys())

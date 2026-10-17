from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils.html import escape
from shop.models import Product
from shop.utils import change_cart_line, get_user_cart

# Single source of truth for shipping: used by the cart page and by Stripe checkout.
SHIPPING_COST = Decimal('5.00')


def _session_qty(value):
    """Guest cart values are ints; tolerate the legacy {quantity, price} shape."""
    if isinstance(value, dict):
        value = value.get('quantity', 0)
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def get_session_cart(request):
    raw = request.session.get('cart', {})
    if not isinstance(raw, dict):
        raw = {}
    cart = {str(pid): _session_qty(qty) for pid, qty in raw.items()}
    return {pid: qty for pid, qty in cart.items() if qty > 0}


def merge_session_cart_into_user_cart(request, user):
    """Move a guest's session cart into the user's DB cart (capped by stock)."""
    session_cart = get_session_cart(request)
    if not session_cart:
        return
    cart = get_user_cart(user, create=True)
    for product in Product.objects.filter(id__in=session_cart.keys()):
        change_cart_line(cart, product, add=session_cart[str(product.id)])
    request.session['cart'] = {}
    request.session.modified = True


def get_cart_items(request):
    """Return a list of {'product', 'quantity', 'subtotal'} dicts for the current visitor."""
    if request.user.is_authenticated:
        cart = get_user_cart(request.user)
        if not cart:
            return []
        return [
            {'product': i.product, 'quantity': i.quantity, 'subtotal': i.subtotal()}
            for i in cart.items.select_related('product')
        ]
    session_cart = get_session_cart(request)
    products = Product.objects.filter(id__in=session_cart.keys())
    return [
        {
            'product': p,
            'quantity': session_cart[str(p.id)],
            'subtotal': p.price * session_cart[str(p.id)],
        }
        for p in products
    ]


def _cart_context(request):
    cart_items = get_cart_items(request)
    subtotal = sum((i['subtotal'] for i in cart_items), Decimal('0.00'))
    shipping = SHIPPING_COST if cart_items else Decimal('0.00')
    has_stock_issue = any(i['quantity'] > i['product'].stock for i in cart_items)
    return {
        'cart_items': cart_items,
        'shipping_cost': shipping,
        'subtotal': subtotal,
        'total': subtotal + shipping,
        'has_stock_issue': has_stock_issue,
    }


def _cart_count(request):
    return sum(i['quantity'] for i in get_cart_items(request))


def cart(request):
    return render(request, 'a_shop/cart.html', _cart_context(request))


def _parse_quantity(raw, default=1):
    try:
        qty = int(raw if raw not in (None, '') else default)
    except (TypeError, ValueError):
        return None
    return qty if qty > 0 else None


def _toast(message, level=None):
    return render_to_string("a_shop/partials/toast.html", {"message": message, "level": level})


def add_to_cart(request, product_id):
    if request.method != 'POST':
        return redirect('cart')

    product = get_object_or_404(Product, id=product_id)
    quantity = _parse_quantity(request.POST.get('quantity', 1))
    unavailable_btn = (
        f'<div id="add-to-cart-btn-{escape(product.id)}">'
        '<button class="btn btn-secondary w-100" disabled>{label}</button></div>'
    )

    if quantity is None:
        # Only show the toast; keep the existing button in place.
        response = HttpResponse(_toast("Please choose a valid quantity.", level="warning"))
        response['HX-Reswap'] = 'none'
        return response

    if product.stock <= 0:
        cart_count_html = render_to_string("a_shop/partials/cart_count.html", {"cart_count": _cart_count(request)})
        return HttpResponse(
            unavailable_btn.replace('{label}', 'Out of stock')
            + cart_count_html
            + _toast("Sorry, this product is out of stock.", level="warning")
        )

    if request.user.is_authenticated:
        cart = get_user_cart(request.user, create=True)
        existing, new_qty = change_cart_line(cart, product, add=quantity)
    else:
        cart_data = get_session_cart(request)
        existing = cart_data.get(str(product_id), 0)
        new_qty = min(existing + quantity, product.stock)
        cart_data[str(product_id)] = new_qty
        request.session['cart'] = cart_data
        request.session.modified = True

    added = new_qty - existing
    total_items = _cart_count(request)

    if added < quantity:
        message = (
            f"Only {product.stock} in stock; your cart now has {new_qty}. "
            "<a href='/cart/' class='text-white text-decoration-underline'>View cart</a>."
        )
    else:
        message = (
            f"Added {quantity} &times; {escape(product.name)} to your cart. "
            "<a href='/cart/' class='text-white text-decoration-underline'>View cart</a>"
        )
    button_html = render_to_string(
        "a_shop/partials/add_to_cart_button.html",
        {
            "product": product,
            "added": True,
        },
    )
    cart_count_html = render_to_string("a_shop/partials/cart_count.html", {"cart_count": total_items})
    return HttpResponse(button_html + cart_count_html + _toast(message))


def _render_cart_fragment(request):
    context = _cart_context(request)
    context['cart_count'] = sum(i['quantity'] for i in context['cart_items'])
    context['oob_count'] = True
    return render(request, "a_shop/partials/cart_items.html", context)


def update_cart_item(request, product_id):
    """Set the quantity of a cart line (HTMX); quantity is capped by stock, 0 removes."""
    if request.method != "POST":
        return redirect("cart")
    product = get_object_or_404(Product, id=product_id)
    try:
        qty = int(request.POST.get('quantity', 1))
    except (TypeError, ValueError):
        qty = 1
    qty = max(0, min(qty, product.stock))

    if request.user.is_authenticated:
        cart = get_user_cart(request.user)
        if cart and cart.items.filter(product=product).exists():
            change_cart_line(cart, product, quantity=qty)
    else:
        cart_data = get_session_cart(request)
        if str(product_id) in cart_data:
            if qty == 0:
                del cart_data[str(product_id)]
            else:
                cart_data[str(product_id)] = qty
            request.session['cart'] = cart_data
            request.session.modified = True
    return _render_cart_fragment(request)


def remove_from_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if request.method == "POST":
        if request.user.is_authenticated:
            cart = get_user_cart(request.user)
            if cart:
                cart.items.filter(product=product).delete()
        else:
            cart_data = get_session_cart(request)
            cart_data.pop(str(product_id), None)
            request.session['cart'] = cart_data
            request.session.modified = True
        return _render_cart_fragment(request)

    return redirect("cart")

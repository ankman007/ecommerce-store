from .models import Cart

def cart_count(request):
    count = 0
    if 'cart' not in request.session:
        request.session['cart'] = {}

    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        if cart:
            count = sum(item.quantity for item in cart.items.all())
    else:
        session_cart = request.session.get('cart', {})
        count = sum(session_cart.values())
    return {'cart_count': count}


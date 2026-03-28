from shop.models import Cart

def check_product_for_cart(request):
    cart_product_ids = set()
    if request.user.is_authenticated:
        try:
            cart = Cart.objects.get(user=request.user)
            cart_product_ids = set(cart.items.values_list('product_id', flat=True))
        except Cart.DoesNotExist:
            cart_product_ids = set()
    else:
        session_cart = request.session.get('cart', {})
        cart_product_ids = set(pid for pid in session_cart.keys())
    
    return cart_product_ids
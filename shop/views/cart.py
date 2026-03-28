from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.template.loader import render_to_string
from shop.models import Product, Cart, CartItem
from loguru import logger

def cart(request):
    cart_items = []

    if request.user.is_authenticated:
        try:
            cart = Cart.objects.get(user=request.user)
            cart_items = cart.items.select_related('product').all()
        except Cart.DoesNotExist:
            cart_items = []
        subtotal = sum(item.product.price * item.quantity for item in cart_items)
    else:
        session_cart = request.session.get('cart', {})
        product_ids = session_cart.keys()
        products = Product.objects.filter(id__in=product_ids)
        quantity_map = {pid: qty for pid, qty in session_cart.items()}
        cart_items = [
            {'product': product, 'quantity': quantity_map[product.id]}
            for product in products
        ]
        subtotal = sum(item['product'].price * item['quantity'] for item in cart_items)

    shipping = 5.00
    total = float(subtotal) + float(shipping)

    return render(request, 'a_shop/cart.html', {
        'cart_items': cart_items,
        'shipping_cost': shipping,
        'subtotal': subtotal,
        'total': total,
    })


def add_to_cart(request, product_id):
    if request.method == 'POST':
        quantity = int(request.POST.get('quantity', 1))
        product = get_object_or_404(Product, id=product_id)

        if request.user.is_authenticated:
            cart, _ = Cart.objects.get_or_create(user=request.user)
            item, created = CartItem.objects.get_or_create(
                cart=cart, 
                product=product,
                defaults={'quantity': quantity}
            )

            if not created:
                item.quantity += quantity
                item.save()
            total_items = sum(i.quantity for i in cart.items.all())
        else:
            cart_data = request.session.get('cart', {})
            old_qty = cart_data.get(str(product_id), 0)
            cart_data[str(product_id)] = old_qty + quantity
            request.session['cart'] = cart_data
            total_items = sum(cart_data.values())

        message = f"Product has been added to your cart (quantity: {quantity}). <a href='/cart/' class='text-white text-decoration-underline'>Click here to checkout</a>."        
        toast_html = render_to_string("a_shop/partials/toast.html", {
            "message": message,
        })
        button_html = render_to_string("a_shop/partials/add_to_cart_button.html", {
            "product": product,
            "added": True,
        })
        cart_count_html = render_to_string("a_shop/partials/cart_count.html", {
            "cart_count": total_items
        })
        return HttpResponse(button_html + cart_count_html + toast_html)

    return redirect('cart')


def remove_from_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if request.method == "POST":
        if request.user.is_authenticated:
            try:
                cart = Cart.objects.get(user=request.user)
                cart_item = cart.items.get(product=product)
                cart_item.delete()
                cart_items = cart.items.select_related('product')
            except (Cart.DoesNotExist, CartItem.DoesNotExist):
                cart_items = []
        else:
            cart = request.session.get('cart', {})
            product_id_str = str(product_id)
            if product_id_str in cart:
                del cart[product_id_str]
                request.session['cart'] = cart

            cart_items = []
            for pid, data in cart.items():
                prod = Product.objects.filter(id=pid).first()
                if prod:
                    cart_items.append({'product': prod, 'quantity': data})


        return render(request, "a_shop/partials/cart_items.html", {"cart_items": cart_items})

    return redirect("cart")


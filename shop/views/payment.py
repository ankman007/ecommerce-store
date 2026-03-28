from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import redirect, render
from django.http import HttpResponseBadRequest
import stripe
from django.conf import settings
from django.template.loader import render_to_string
from django.contrib import messages
from shop.models import Order, OrderItem, Product, Cart
from shop.tasks import create_order_task

stripe.api_key = settings.STRIPE_SECRET_KEY


def create_checkout_session(request):
    if request.method == "POST":
        item_names = request.POST.getlist("items_name")
        item_prices = request.POST.getlist("items_price")
        item_quantities = request.POST.getlist("items_quantity")

        if not item_names or not item_prices or not item_quantities:
            return HttpResponseBadRequest("Missing form data")

        line_items = []
        cart = {}

        for name, price, quantity in zip(item_names, item_prices, item_quantities):
            try:
                product = Product.objects.get(name=name)
                line_items.append({
                    'price_data': {
                        'currency': 'usd',
                        'unit_amount': int(float(price) * 100),
                        'product_data': {
                            'name': name,
                        },
                    },
                    'quantity': int(quantity),
                })
                cart[str(product.id)] = {
                    'quantity': int(quantity),
                    'price': float(price),
                }
            except (Product.DoesNotExist, ValueError):
                return HttpResponseBadRequest("Invalid product or data")

        request.session['cart'] = cart
        request.session.modified = True

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url='http://localhost:8000/success/',
            cancel_url='http://localhost:8000/cancel/',
        )
        return redirect(checkout_session.url)

    return HttpResponseBadRequest("Invalid request method")


def success(request):
    cart = request.session.get('cart', {})

    if not cart:
        messages.error(request, "🛒 Cart is empty or expired.")
        return redirect('home')

    user_id = request.user.id if request.user.is_authenticated else None
    create_order_task.delay(user_id, cart)

    if 'cart' in request.session:
        del request.session['cart']
        request.session.modified = True

    toast_message = "✅ Payment successful! Your order has been placed."
    toast_html = render_to_string("a_shop/partials/toast.html", {"message": toast_message})
    messages.success(request, toast_html)
    return redirect('home')


def cancel(request):
    toast_message = "❌ Payment was canceled. <a href='/cart/' class='underline'>Return to cart</a> to try again."
    toast_html = render_to_string("a_shop/partials/toast.html", {"message": toast_message})
    messages.error(request, toast_html)
    return redirect('home')

import os
from datetime import timedelta
from functools import partial
from decimal import Decimal

import stripe
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from loguru import logger

from shop.forms import ShippingAddressForm
from shop.models import Order, OrderItem, Product, CartItem
from shop.tasks import send_order_confirmation, send_order_status_email
from shop.views.cart import SHIPPING_COST, get_user_cart

stripe.api_key = settings.STRIPE_SECRET_KEY


def _field(obj, key):
    """Read a field from a Stripe object or a plain dict."""
    try:
        return obj[key]
    except (KeyError, TypeError, AttributeError):
        return getattr(obj, key, None)


def _to_cents(amount):
    return int((Decimal(amount) * 100).quantize(Decimal('1')))


# Stripe's minimum is 30 minutes; pending orders past this are cleaned up by
# shop.tasks.expire_stale_checkouts.
CHECKOUT_SESSION_TTL = timedelta(minutes=60)


def _flag_for_review(order, reason):
    """Mark an order for manual review and email the shop once the transaction commits."""
    from shop.tasks import notify_order_needs_review

    order.status = Order.STATUS_NEEDS_REVIEW
    order.save(update_fields=['status'])
    transaction.on_commit(lambda: notify_order_needs_review.delay(order.id, reason))


def _toast(message):
    return render_to_string("a_shop/partials/toast.html", {"message": message})


def _checkout_cart_items(request):
    """Validate the user's DB cart for checkout. Returns (items, error_redirect)."""
    cart = get_user_cart(request.user)
    items = list(cart.items.select_related('product')) if cart else []
    if not items:
        messages.error(request, _toast("Your cart is empty."))
        return None, redirect('cart')
    for item in items:
        if item.quantity < 1 or item.product.stock < item.quantity:
            messages.error(
                request,
                _toast(f"Sorry, only {item.product.stock} of {item.product.name} in stock. Please update your cart."),
            )
            return None, redirect('cart')
    return items, None


def _initial_address(user):
    """Prefill the address form from the user's most recent order that has an address."""
    last = (
        Order.objects.filter(user=user)
        .exclude(address_line1='')
        .order_by('-created_at')
        .values(*Order.ADDRESS_FIELDS)
        .first()
    )
    if last:
        return last
    return {'full_name': user.get_full_name(), 'country': 'US'}


def _render_address_page(request, form, items, status=200):
    subtotal = sum((item.product.price * item.quantity for item in items), Decimal('0.00'))
    context = {
        'form': form,
        'items': items,
        'subtotal': subtotal,
        'shipping_cost': SHIPPING_COST,
        'total': subtotal + SHIPPING_COST,
    }
    return render(request, 'a_shop/checkout.html', context, status=status)


def checkout_address(request):
    """Checkout step 1: collect the shipping address and phone, then start Stripe Checkout."""
    if not request.user.is_authenticated:
        return redirect(f"{reverse('account_login')}?next={reverse('checkout_address')}")
    if request.method == "POST":
        return create_checkout_session(request)
    items, error = _checkout_cart_items(request)
    if error:
        return error
    form = ShippingAddressForm(initial=_initial_address(request.user))
    return _render_address_page(request, form, items)


def create_checkout_session(request):
    # GET (e.g. after "Login to Checkout") → send the user to their cart instead of a 400.
    if request.method != "POST":
        return redirect('cart')
    if not request.user.is_authenticated:
        return redirect(f"{reverse('account_login')}?next={reverse('cart')}")

    # Everything below is built from the DB cart; client-posted item fields are ignored.
    items, error = _checkout_cart_items(request)
    if error:
        return error

    form = ShippingAddressForm(request.POST)
    if not form.is_valid():
        return _render_address_page(request, form, items, status=400 if request.POST else 200)
    address = {field: form.cleaned_data.get(field) or '' for field in Order.ADDRESS_FIELDS}

    subtotal = sum((item.product.price * item.quantity for item in items), Decimal('0.00'))
    shipping = SHIPPING_COST
    with transaction.atomic():
        order = Order.objects.create(
            user=request.user,
            status=Order.STATUS_PENDING,
            paid=False,
            shipping_cost=shipping,
            total=subtotal + shipping,
            **address,
        )
        OrderItem.objects.bulk_create(
            [
                OrderItem(order=order, product=item.product, quantity=item.quantity, price=item.product.price)
                for item in items
            ]
        )

    line_items = [
        {
            'price_data': {
                'currency': 'usd',
                'unit_amount': _to_cents(item.product.price),
                'product_data': {'name': item.product.name},
            },
            'quantity': item.quantity,
        }
        for item in items
    ]
    if shipping:
        line_items.append(
            {
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': _to_cents(shipping),
                    'product_data': {'name': 'Shipping'},
                },
                'quantity': 1,
            }
        )

    try:
        checkout_session = stripe.checkout.Session.create(
            line_items=line_items,
            mode='payment',
            client_reference_id=str(order.id),
            metadata={'order_id': str(order.id)},
            customer_email=request.user.email or None,
            success_url=request.build_absolute_uri(reverse('success')) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.build_absolute_uri(reverse('cancel')),
            expires_at=int((timezone.now() + CHECKOUT_SESSION_TTL).timestamp()),
            payment_intent_data={'shipping': _stripe_shipping(order)},
        )
    except stripe.StripeError:
        logger.exception("Stripe checkout session creation failed for order {}", order.id)
        order.status = Order.STATUS_CANCELLED
        order.save(update_fields=['status'])
        messages.error(request, _toast("Payment provider error. Please try again."))
        return redirect('cart')

    order.stripe_session_id = _field(checkout_session, 'id')
    order.save(update_fields=['stripe_session_id'])
    return redirect(_field(checkout_session, 'url'))


def _stripe_shipping(order):
    """The order's address snapshot in Stripe's `shipping` shape (shown on the payment in Stripe)."""
    address = {
        'line1': order.address_line1,
        'line2': order.address_line2,
        'city': order.city,
        'state': order.state,
        'postal_code': order.postal_code,
        'country': order.country,
    }
    return {
        'name': order.full_name,
        'phone': order.phone,
        'address': {key: value for key, value in address.items() if value},
    }


def fulfill_checkout_session(checkout_session):
    """Idempotently mark the order for a paid Stripe Checkout Session as paid.

    Returns (order, result) where result is one of:
    'paid' (processed now; the order may be flagged needs_review if stock ran out),
    'already_paid', 'unpaid', 'not_found', 'amount_mismatch'.
    Shared by the success redirect, the webhook and the stale-checkout cleanup task.
    """
    session_id = _field(checkout_session, 'id')
    if not session_id:
        return None, 'not_found'
    if _field(checkout_session, 'payment_status') != 'paid':
        return None, 'unpaid'

    with transaction.atomic():
        order = Order.objects.select_for_update().filter(stripe_session_id=session_id).first()
        if order is None:
            return None, 'not_found'
        if order.paid:
            return order, 'already_paid'

        order.stripe_payment_intent = _field(checkout_session, 'payment_intent') or order.stripe_payment_intent
        order.save(update_fields=['stripe_payment_intent'])

        amount_total = _field(checkout_session, 'amount_total')
        if amount_total is not None and int(amount_total) != _to_cents(order.total):
            logger.error(
                "Amount mismatch for order {}: stripe={} expected={}", order.id, amount_total, _to_cents(order.total)
            )
            # The customer was charged, so don't leave this silently pending: a person must check it.
            if order.status != Order.STATUS_NEEDS_REVIEW:
                _flag_for_review(order, f"Stripe charged {amount_total} cents but the order total is {order.total}.")
            return order, 'amount_mismatch'

        oversold = []
        for item in order.items.all():
            if not item.product_id:
                continue
            updated = Product.objects.filter(pk=item.product_id, stock__gte=item.quantity).update(
                stock=F('stock') - item.quantity
            )
            if not updated:
                # Paid but oversold (concurrent purchase): never go negative; flag for review.
                Product.objects.filter(pk=item.product_id).update(stock=0)
                logger.warning("Order {} oversold product {}; needs manual review", order.id, item.product_id)
                oversold.append(str(item))

        order.paid = True
        order.status = Order.STATUS_PAID
        order.paid_at = timezone.now()
        order.save(update_fields=['paid', 'status', 'paid_at'])
        # Only reached once per order (paid is checked under the row lock above); the task
        # also claims confirmation_sent_at, so a re-delivered webhook can never email twice.
        transaction.on_commit(partial(send_order_confirmation.delay, order.id))
        if oversold:
            _flag_for_review(order, "Paid, but stock ran out for: " + ", ".join(oversold))

        if order.user_id:
            product_ids = [i.product_id for i in order.items.all() if i.product_id]
            CartItem.objects.filter(cart__user_id=order.user_id, product_id__in=product_ids).delete()

    return order, 'paid'


def success(request):
    session_id = request.GET.get('session_id')
    if not session_id:
        messages.error(request, _toast("Invalid payment confirmation."))
        return redirect('home')
    if not request.user.is_authenticated:
        return redirect(f"{reverse('account_login')}?next={request.get_full_path()}")

    order = Order.objects.filter(stripe_session_id=session_id, user=request.user).first()
    if order is None:
        messages.error(request, _toast("Order not found."))
        return redirect('home')

    if not order.paid:
        try:
            checkout_session = stripe.checkout.Session.retrieve(session_id)
        except stripe.StripeError:
            logger.exception("Could not retrieve Stripe session {}", session_id)
            messages.error(
                request, _toast("Could not verify payment. If you were charged, your order will be confirmed shortly.")
            )
            return redirect('orders')
        _, result = fulfill_checkout_session(checkout_session)
        if result not in ('paid', 'already_paid'):
            messages.error(request, _toast("Payment has not been completed."))
            return redirect('cart')

    return redirect(f"{reverse('order_detail', args=[order.id])}?placed=1")


def _webhook_secret():
    return getattr(settings, 'STRIPE_WEBHOOK_SECRET', None) or os.getenv('STRIPE_WEBHOOK_SECRET')


@csrf_exempt
@require_POST
def stripe_webhook(request):
    secret = _webhook_secret()
    signature = request.META.get('HTTP_STRIPE_SIGNATURE')
    if not secret or not signature:
        return HttpResponseBadRequest("Webhook not configured or unsigned")
    try:
        event = stripe.Webhook.construct_event(request.body, signature, secret)
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponseBadRequest("Invalid signature")

    event_type = _field(event, 'type')
    checkout_session = _field(_field(event, 'data'), 'object')
    if event_type in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        fulfill_checkout_session(checkout_session)
    elif event_type in ('checkout.session.expired', 'checkout.session.async_payment_failed'):
        cancel_unpaid_order(_field(checkout_session, 'id'))
    return HttpResponse(status=200)


def cancel_unpaid_order(session_id):
    """Cancel the pending order for a Checkout Session that can no longer be paid. Idempotent."""
    if not session_id:
        return None
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(stripe_session_id=session_id).first()
        if order is None or order.paid or order.status != Order.STATUS_PENDING:
            return order
        order.status = Order.STATUS_CANCELLED
        order.save(update_fields=['status'])
    return order


def cancel(request):
    messages.info(
        request,
        _toast(
            "Payment cancelled &mdash; you haven't been charged. Your cart is saved, so you can check out whenever you're ready."
        ),
    )
    return redirect('cart')


REFUNDABLE_STATUSES = (Order.STATUS_PAID, Order.STATUS_NEEDS_REVIEW, Order.STATUS_SHIPPED)


def refund_order(order):
    """Fully refund an order's Stripe payment and mark it refunded.

    Uses an idempotency key, so retrying (or a double-click in the admin) never refunds twice.
    Stock is not restored automatically. Raises ValueError if the order can't be refunded.
    """
    if order.status not in REFUNDABLE_STATUSES:
        raise ValueError(f"order is {order.get_status_display().lower()}")
    if not order.stripe_payment_intent:
        raise ValueError("no Stripe payment is recorded for this order")
    stripe.Refund.create(payment_intent=order.stripe_payment_intent, idempotency_key=f"refund-order-{order.pk}")
    order.status = Order.STATUS_REFUNDED
    order.save(update_fields=['status'])
    transaction.on_commit(partial(send_order_status_email.delay, order.id, 'refunded'))
    return order

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, mail_admins, send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from loguru import logger


@shared_task
def send_contact_email(sender_email, subject, message):
    full_message = f"From: <{sender_email}>\n\n{message}"
    send_mail(
        subject,
        full_message,
        settings.DEFAULT_FROM_EMAIL,
        [settings.RECIPIENT_EMAIL],
    )


# Order creation/fulfilment is synchronous now (see shop.views.payment.fulfill_checkout_session);
# the old create_order_task created PAID orders from untrusted session data and was removed.


@shared_task
def notify_order_needs_review(order_id, reason):
    """Email the shop that a paid order needs a person to look at it (stock ran out, amount mismatch)."""
    recipient = settings.RECIPIENT_EMAIL
    subject = f"Order #{order_id} needs review"
    body = (
        f"{reason}\n\n"
        "Open the order in the admin, then either fulfil it (action: 'Mark reviewed') "
        "or refund it (action: 'Refund via Stripe')."
    )
    if recipient:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient])
    else:
        try:
            mail_admins(subject, body)
        except Exception:
            logger.exception("Could not email admins about order {}", order_id)


def _from_email():
    # DEFAULT_FROM_EMAIL already falls back to the EMAIL_HOST_USER env var (core/settings.py)
    return settings.DEFAULT_FROM_EMAIL


def site_url():
    """Absolute base URL for links in emails: settings.SITE_URL, else the Sites framework domain."""
    configured = getattr(settings, 'SITE_URL', None)
    if configured:
        return configured.rstrip('/')
    from django.contrib.sites.models import Site

    protocol = getattr(settings, 'ACCOUNT_DEFAULT_HTTP_PROTOCOL', 'https')
    return f"{protocol}://{Site.objects.get_current().domain}"


def _send_order_email(order, template, subject):
    """Render a_shop/emails/<template>.txt/.html for the order and send it to the customer."""
    recipient = order.user.email if order.user else ''
    if not recipient:
        logger.warning("Order {} has no customer email; '{}' email not sent", order.id, template)
        return False
    base = site_url()
    context = {
        'order': order,
        'items': list(order.items.select_related('product').order_by('id')),
        'site_url': base,
        'order_url': base + reverse('order_detail', args=[order.id]),
        'customer_name': order.full_name or order.user.get_full_name() or order.user.username,
    }
    message = EmailMultiAlternatives(
        subject,
        render_to_string(f'a_shop/emails/{template}.txt', context),
        _from_email(),
        [recipient],
    )
    message.attach_alternative(render_to_string(f'a_shop/emails/{template}.html', context), 'text/html')
    message.send(fail_silently=False)
    return True


@shared_task
def send_order_confirmation(order_id):
    """Email the customer their order confirmation, at most once per order."""
    from shop.models import Order

    # Claim the send first, so repeated or concurrent fulfilment can never email twice.
    claimed = Order.objects.filter(pk=order_id, paid=True, confirmation_sent_at__isnull=True).update(
        confirmation_sent_at=timezone.now()
    )
    if not claimed:
        return False
    order = Order.objects.select_related('user').get(pk=order_id)
    try:
        return _send_order_email(order, 'order_confirmation', f"Order #{order.id} confirmed")
    except Exception:
        # Release the claim so a retry can send it.
        Order.objects.filter(pk=order_id).update(confirmation_sent_at=None)
        raise


ORDER_STATUS_EMAILS = {
    'shipped': ('order_shipped', 'Your order #{id} has shipped'),
    'refunded': ('order_refunded', 'Your order #{id} has been refunded'),
}


@shared_task
def send_order_status_email(order_id, kind):
    """Tell the customer their order was shipped or refunded."""
    from shop.models import Order

    template, subject = ORDER_STATUS_EMAILS[kind]
    order = Order.objects.select_related('user').filter(pk=order_id).first()
    if order is None:
        return False
    return _send_order_email(order, template, subject.format(id=order.id))


@shared_task
def expire_stale_checkouts():
    """Resolve pending orders whose Stripe Checkout Session should have finished by now.

    Runs periodically (CELERY_BEAT_SCHEDULE). For each stale pending order the session is
    checked with Stripe instead of being cancelled blindly, so a payment whose webhook was
    missed is still fulfilled:
      - paid       -> fulfilled
      - still open -> expired on Stripe, order cancelled
      - expired    -> order cancelled
    """
    import stripe

    from shop.models import Order
    from shop.views.payment import CHECKOUT_SESSION_TTL, cancel_unpaid_order, fulfill_checkout_session

    cutoff = timezone.now() - CHECKOUT_SESSION_TTL - timedelta(minutes=15)
    stale = Order.objects.filter(status=Order.STATUS_PENDING, created_at__lt=cutoff)
    counts = {'fulfilled': 0, 'cancelled': 0, 'errors': 0}

    for order in stale.iterator():
        if not order.stripe_session_id:
            # Never reached Stripe (e.g. session creation failed).
            Order.objects.filter(pk=order.pk, status=Order.STATUS_PENDING).update(status=Order.STATUS_CANCELLED)
            counts['cancelled'] += 1
            continue
        try:
            session = stripe.checkout.Session.retrieve(order.stripe_session_id)
            if session['payment_status'] == 'paid':
                fulfill_checkout_session(session)
                counts['fulfilled'] += 1
                continue
            if session['status'] == 'open':
                stripe.checkout.Session.expire(order.stripe_session_id)
            cancel_unpaid_order(order.stripe_session_id)
            counts['cancelled'] += 1
        except stripe.StripeError:
            logger.exception("Could not resolve stale checkout for order {}", order.id)
            counts['errors'] += 1

    if any(counts.values()):
        logger.info("Stale checkout cleanup: {}", counts)
    return counts

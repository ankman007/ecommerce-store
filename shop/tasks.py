from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import mail_admins, send_mail
from django.utils import timezone
from loguru import logger


@shared_task
def send_contact_email(sender_email, subject, message):
    full_message = f"From: <{sender_email}>\n\n{message}"
    send_mail(
        subject,
        full_message,
        settings.EMAIL_HOST_USER,
        [settings.RECIPIENT_EMAIL],
        fail_silently=False,
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
        send_mail(subject, body, settings.EMAIL_HOST_USER, [recipient], fail_silently=False)
    else:
        mail_admins(subject, body, fail_silently=True)


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

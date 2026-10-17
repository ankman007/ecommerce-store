from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings

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

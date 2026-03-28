from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from shop.models import Order, OrderItem, Product, Cart
from django.contrib.auth import get_user_model

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


@shared_task
def create_order_task(user_id, cart_data):
    User = get_user_model()
    user = User.objects.filter(id=user_id).first() if user_id else None

    order = Order.objects.create(user=user, paid=True)

    for product_id, item in cart_data.items():
        try:
            product = Product.objects.get(pk=product_id)
            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=item['quantity'],
                price=item['price']
            )
        except Product.DoesNotExist:
            continue

    if user:
        try:
            user_cart = Cart.objects.get(user=user)
            user_cart.items.all().delete()
        except Cart.DoesNotExist:
            pass
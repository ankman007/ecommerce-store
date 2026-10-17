from allauth.account.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in, dispatch_uid="shop_merge_guest_cart")
def merge_guest_cart_on_login(sender, request, user, **kwargs):
    """Merge the guest's session cart into their DB cart when they log in."""
    if request is None or not hasattr(request, 'session'):
        return
    from shop.views.cart import merge_session_cart_into_user_cart

    merge_session_cart_into_user_cart(request, user)

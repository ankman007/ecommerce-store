from django.urls import path
from .views import base, cart, category, product, payment, order


urlpatterns = [
    path('', base.home, name='home'),
    path('contact/', base.contact, name='contact'),
    path('contact/success/', base.contact_success, name='contact_success'),

    path('about/', base.about, name='about'),
    path('privacy-policy/', base.privacy_policy, name='privacy_policy'),
    
    path('product/<str:id>', product.product_detail, name='product_detail'),
    path('search/', product.product_search, name='product-search'),
    
    path('category/<slug:slug>', category.category, name='category'),
    
    path('cart/', cart.cart, name='cart'),
    path('add-to-cart/<str:product_id>/', cart.add_to_cart, name='add_to_cart'),
    path('cart/remove/<str:product_id>/', cart.remove_from_cart, name='remove_from_cart'),
    path('cart/update/<str:product_id>/', cart.update_cart_item, name='update_cart_item'),

    path('create-checkout-session/', payment.create_checkout_session, name='checkout'),
    path('success/', payment.success, name='success'),
    path('cancel/', payment.cancel, name='cancel'),
    path('stripe/webhook/', payment.stripe_webhook, name='stripe_webhook'),
    
    path('orders/', order.order, name='orders'),
    path('orders/<int:order_id>/', order.order_detail, name='order_detail'),
]


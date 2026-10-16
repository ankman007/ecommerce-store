from django.apps import AppConfig


class AEcommerceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'shop'
    # Keep the original label so existing DB tables and migrations still match
    label = 'a_shop'
    

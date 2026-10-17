from django.apps import AppConfig


class AEcommerceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'shop'
    # Keep the original label so existing DB tables and migrations still match
    label = 'a_shop'

    def ready(self):
        from . import signals  # noqa: F401  (connects receivers)

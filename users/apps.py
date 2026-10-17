from django.apps import AppConfig


class AUsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'users'
    # Keep the original label so existing DB tables and migrations still match
    label = 'a_users'
    
    def ready(self):
        import users.signals  # noqa: F401  (registers signal receivers)

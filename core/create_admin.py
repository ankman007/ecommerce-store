import os
import sys
from dotenv import load_dotenv

sys.path.append('/app')

load_dotenv()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.getenv("DJANGO_SETTINGS_MODULE", "a_core.settings"))

import django
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()
username = os.getenv("ADMIN_USERNAME")
email = os.getenv("ADMIN_EMAIL")
password = os.getenv("ADMIN_PASSWORD")

if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, email=email, password=password)
    print(f"✅ Superuser '{username}' created.")
else:
    print(f"ℹ️ Superuser '{username}' already exists.")

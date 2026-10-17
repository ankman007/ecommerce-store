import os
import sys

from dotenv import load_dotenv

sys.path.append('/app')

load_dotenv()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.getenv("DJANGO_SETTINGS_MODULE", "core.settings"))

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402

from users.models import Profile  # noqa: E402


def main():
    User = get_user_model()
    username = (os.getenv("ADMIN_USERNAME") or "").strip()
    email = (os.getenv("ADMIN_EMAIL") or "").strip()
    password = os.getenv("ADMIN_PASSWORD") or ""

    if not username or not password:
        print("ADMIN_USERNAME / ADMIN_PASSWORD not set; skipping superuser creation.")
        return

    # Usernames are stored lowercase by the users pre_save signal
    user = User.objects.filter(username__iexact=username).first()
    if user is None:
        user = User.objects.create_superuser(username=username, email=email, password=password)
        print(f"Superuser '{user.username}' created.")
    else:
        print(f"Superuser '{user.username}' already exists.")

    # Ensure the admin has a profile (users created before the signal may not)
    Profile.objects.get_or_create(user=user)


if __name__ == "__main__":
    main()

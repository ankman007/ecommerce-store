from allauth.account.models import EmailAddress
from django.contrib.auth.models import User
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Profile


@receiver(post_save, sender=User)
def user_postsave(sender, instance, created, raw=False, **kwargs):
    if raw:  # skip during fixture loading
        return
    user = instance

    # Ensure every user has a profile
    if created:
        Profile.objects.get_or_create(user=user)
        return

    # Keep allauth's primary EmailAddress in sync with user.email
    if not user.email:
        return

    primary = EmailAddress.objects.filter(user=user, primary=True).first()
    if primary and primary.email.lower() == user.email.lower():
        return

    existing = EmailAddress.objects.filter(user=user, email__iexact=user.email).first()
    if existing:
        # Promote the existing record for this email to primary
        if primary:
            primary.primary = False
            primary.save(update_fields=['primary'])
        existing.primary = True
        existing.save(update_fields=['primary'])
    elif primary:
        # Email changed: update the primary record and require re-verification
        primary.email = user.email
        primary.verified = False
        primary.save(update_fields=['email', 'verified'])
    else:
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=False)


@receiver(pre_save, sender=User)
def user_presave(sender, instance, **kwargs):
    if instance.username:
        instance.username = instance.username.lower()

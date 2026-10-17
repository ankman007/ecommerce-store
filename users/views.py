from allauth.account.models import EmailAddress
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .forms import EmailForm, ProfileForm, UsernameForm
from .models import Profile


def _get_profile(user):
    """Return the user's profile, creating it if missing (e.g. users created
    before the signal existed or via raw shell/fixtures)."""
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def profile_view(request, username=None):
    if username:
        user = get_object_or_404(User, username__iexact=username)
    elif request.user.is_authenticated:
        user = request.user
    else:
        return redirect_to_login(request.get_full_path())
    profile = _get_profile(user)
    return render(request, 'a_users/profile.html', {'profile': profile})


@login_required
def profile_edit_view(request):
    profile = _get_profile(request.user)
    form = ProfileForm(instance=profile)

    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated.')
            return redirect('profile')

    onboarding = request.path == reverse('profile-onboarding')

    return render(request, 'a_users/profile_edit.html', {'form': form, 'onboarding': onboarding})


@login_required
def profile_settings_view(request):
    return render(request, 'a_users/profile_settings.html')


def _form_errors(form):
    return ' '.join(str(e) for errors in form.errors.values() for e in errors)


@login_required
@require_http_methods(['GET', 'POST'])
def profile_emailchange(request):
    if request.method == 'GET':
        if request.htmx:
            form = EmailForm(instance=request.user)
            return render(request, 'partials/email_form.html', {'form': form})
        return redirect('profile-settings')

    form = EmailForm(request.POST, instance=request.user)
    if form.is_valid():
        if 'email' not in form.changed_data:
            return redirect('profile-settings')
        form.save()
        # Signal updates the allauth EmailAddress and marks it unverified
        send_email_confirmation(request)
        messages.success(request, 'Email updated. Please check your inbox to verify it.')
    else:
        messages.warning(request, _form_errors(form) or 'Email not valid or already in use')
    return redirect('profile-settings')


@login_required
@require_http_methods(['GET', 'POST'])
def profile_usernamechange(request):
    if request.method == 'GET':
        if request.htmx:
            form = UsernameForm(instance=request.user)
            return render(request, 'partials/username_form.html', {'form': form})
        return redirect('profile-settings')

    form = UsernameForm(request.POST, instance=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, 'Username updated successfully.')
    else:
        messages.warning(request, _form_errors(form) or 'Username not valid or already in use')
    return redirect('profile-settings')


@login_required
def profile_emailverify(request):
    send_email_confirmation(request)
    return redirect('profile-settings')


@login_required
def profile_delete_view(request):
    user = request.user
    if request.method == "POST":
        if user.is_superuser:
            messages.warning(request, 'Superuser accounts cannot be deleted from here.')
            return redirect('profile-settings')
        logout(request)
        user.delete()
        messages.success(request, 'Account deleted, what a pity')
        return redirect('home')

    return render(request, 'a_users/profile_delete.html')


def send_email_confirmation(request):
    email_address = EmailAddress.objects.get_primary(request.user)
    if email_address and not email_address.verified:
        email_address.send_confirmation(request)
    elif email_address:
        messages.info(request, 'Your email is already verified.')

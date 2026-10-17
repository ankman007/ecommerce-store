import os

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.forms import ModelForm

from .models import Profile

MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2 MB
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


class ProfileForm(ModelForm):
    class Meta:
        model = Profile
        fields = ['image', 'displayname', 'info']
        widgets = {
            'image': forms.FileInput(attrs={'accept': 'image/*'}),
            'displayname': forms.TextInput(attrs={'placeholder': 'Add display name', 'maxlength': 20}),
            'info': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Add information', 'maxlength': 1000}),
        }

    def clean_image(self):
        image = self.cleaned_data.get('image')
        # Only validate newly uploaded files (existing FieldFile has no content_type)
        if image and hasattr(image, 'content_type'):
            if image.size > MAX_AVATAR_SIZE:
                raise ValidationError('Image file too large (max 2 MB).')
            ext = os.path.splitext(image.name)[1].lower()
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                raise ValidationError('Unsupported image type. Use JPG, PNG, GIF or WebP.')
            if not (image.content_type or '').startswith('image/'):
                raise ValidationError('Uploaded file is not an image.')
        return image

    def clean_displayname(self):
        name = (self.cleaned_data.get('displayname') or '').strip()
        return name or None

    def clean_info(self):
        info = (self.cleaned_data.get('info') or '').strip()
        if len(info) > 1000:
            raise ValidationError('Information must be 1000 characters or fewer.')
        return info or None


class EmailForm(ModelForm):
    email = forms.EmailField(required=True, max_length=254)

    class Meta:
        model = User
        fields = ['email']

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        qs = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(f'{email} is already in use.')
        return email


class UsernameForm(ModelForm):
    username = forms.CharField(
        min_length=3,
        max_length=30,
        validators=[UnicodeUsernameValidator()],
        help_text='3-30 characters. Letters, digits and @/./+/-/_ only.',
    )

    class Meta:
        model = User
        fields = ['username']

    def clean_username(self):
        username = self.cleaned_data['username'].strip().lower()
        qs = User.objects.filter(username__iexact=username)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError(f'{username} is already taken.')
        return username

# forms.py
from django import forms
from django.core.exceptions import ValidationError

INPUT_CLASSES = 'w-full px-4 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring focus:border-blue-400'


def _reject_newlines(value):
    # name/subject end up in email headers; block header injection
    if value and ('\n' in value or '\r' in value):
        raise ValidationError('Line breaks are not allowed in this field.')


class ContactForm(forms.Form):
    name = forms.CharField(
        min_length=2,
        max_length=100,
        strip=True,
        validators=[_reject_newlines],
        widget=forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'Your name'}),
    )
    email = forms.EmailField(
        max_length=254,
        widget=forms.EmailInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'you@example.com'}),
    )
    subject = forms.CharField(
        required=False,
        max_length=150,
        strip=True,
        validators=[_reject_newlines],
        widget=forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'Subject (optional)'}),
    )
    message = forms.CharField(
        min_length=10,
        max_length=5000,
        strip=True,
        widget=forms.Textarea(attrs={
            'class': INPUT_CLASSES,
            'placeholder': 'Write your message here...',
            'rows': 5,
        }),
    )

# forms.py
import re

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
        widget=forms.Textarea(
            attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'Write your message here...',
                'rows': 5,
            }
        ),
    )


# Countries we ship to (ISO 3166-1 alpha-2, as Stripe expects). Extend as needed.
COUNTRY_CHOICES = [
    ('US', 'United States'),
    ('CA', 'Canada'),
    ('GB', 'United Kingdom'),
    ('AU', 'Australia'),
    ('NZ', 'New Zealand'),
    ('IE', 'Ireland'),
    ('DE', 'Germany'),
    ('FR', 'France'),
    ('IN', 'India'),
    ('NP', 'Nepal'),
]
COUNTRY_NAMES = dict(COUNTRY_CHOICES)

_PHONE_RE = re.compile(r'^\+?[0-9 ()./-]{7,25}$')
FIELD_CLASSES = 'form-control'


def _validate_phone(value):
    digits = re.sub(r'\D', '', value)
    if not _PHONE_RE.match(value) or not 7 <= len(digits) <= 15:
        raise ValidationError('Enter a valid phone number, e.g. +1 518 555 0100.')


def _text(label, max_length, required=True, autocomplete=None):
    attrs = {'class': FIELD_CLASSES}
    if autocomplete:
        attrs['autocomplete'] = autocomplete
    return forms.CharField(
        label=label,
        max_length=max_length,
        required=required,
        strip=True,
        validators=[_reject_newlines],
        widget=forms.TextInput(attrs=attrs),
    )


class ShippingAddressForm(forms.Form):
    """Shipping details collected before payment; saved as a snapshot on the Order."""

    full_name = _text('Full name', 120, autocomplete='name')
    phone = forms.CharField(
        label='Phone',
        max_length=30,
        strip=True,
        validators=[_validate_phone],
        widget=forms.TextInput(attrs={'class': FIELD_CLASSES, 'autocomplete': 'tel', 'type': 'tel'}),
    )
    address_line1 = _text('Address line 1', 200, autocomplete='address-line1')
    address_line2 = _text('Address line 2 (optional)', 200, required=False, autocomplete='address-line2')
    city = _text('City', 100, autocomplete='address-level2')
    state = _text('State / region', 100, required=False, autocomplete='address-level1')
    postal_code = _text('Postal code', 20, autocomplete='postal-code')
    country = forms.ChoiceField(
        label='Country',
        choices=COUNTRY_CHOICES,
        initial='US',
        widget=forms.Select(attrs={'class': 'form-select', 'autocomplete': 'country'}),
    )

    def clean_postal_code(self):
        value = self.cleaned_data['postal_code'].upper()
        if not re.fullmatch(r'[A-Z0-9 -]{2,20}', value):
            raise ValidationError('Enter a valid postal code.')
        return value

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('country') == 'US' and not cleaned.get('state'):
            self.add_error('state', 'State is required for US addresses.')
        return cleaned


SORT_CHOICES = [
    ('newest', 'Newest'),
    ('price_asc', 'Price: low to high'),
    ('price_desc', 'Price: high to low'),
    ('name', 'Name: A to Z'),
]


class CatalogFilterForm(forms.Form):
    """Sorting and filtering for product listings (all optional; invalid values are ignored)."""

    sort = forms.ChoiceField(choices=SORT_CHOICES, required=False)
    min_price = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2)
    max_price = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2)
    in_stock = forms.BooleanField(required=False)

"""Convert CKEditor HTML in Product.description to plain text.

django-ckeditor (CKEditor 4, unsupported) was removed. Product.description is now a
plain models.TextField. No schema change is needed: ckeditor's RichTextField was a
TextField subclass, so the column was already a TEXT column, and 0001_initial was
edited to declare models.TextField so old migrations import without the package.

This migration only rewrites existing data: descriptions saved through CKEditor may
contain HTML (<p>, <br>, <strong>, entities). They are converted to plain text with
paragraphs and line breaks kept as newlines. Templates now escape the text and render
newlines with |linebreaksbr. The reverse is a no-op (plain text is valid either way).
"""

import html
import re

from django.db import migrations
from django.utils.html import strip_tags

# Only touch values that actually look like HTML, so real plain text such as
# "AT&T" or "size < 5" is left alone.
_LOOKS_LIKE_HTML = re.compile(r'<\s*/?\s*[a-zA-Z!][^>]*>|&(?:[a-zA-Z]+|#\d+|#x[0-9a-fA-F]+);')
# Each pattern also swallows the source whitespace CKEditor writes after the tag, so a
# break is not counted twice.
_LINE_BREAK = re.compile(r'<\s*br\s*/?\s*>[ \t]*\n?', re.IGNORECASE)
_ROW_END = re.compile(r'<\s*/\s*(?:li|tr)\s*>\s*', re.IGNORECASE)
_BLOCK_END = re.compile(r'<\s*/\s*(?:p|div|h[1-6]|blockquote|pre|ul|ol|table)\s*>\s*', re.IGNORECASE)


def html_to_plain_text(value):
    """Return ``value`` as plain text; values without HTML are only trimmed."""
    if not value:
        return ''
    text = value.replace('\r\n', '\n').replace('\r', '\n')
    if not _LOOKS_LIKE_HTML.search(text):
        return text.strip()
    # Source newlines are kept: the old Product.save() replaced <p>/</p> with spaces,
    # so for already-saved rows the newlines CKEditor put between paragraphs are the
    # only paragraph markers left. Extra blank lines are collapsed below.
    text = _LINE_BREAK.sub('\n', text)
    text = _ROW_END.sub('\n', text)
    text = _BLOCK_END.sub('\n\n', text)
    text = strip_tags(text)
    text = html.unescape(text).replace('\xa0', ' ')
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def convert_descriptions(apps, schema_editor):
    Product = apps.get_model('a_shop', 'Product')
    changed = []
    for product in Product.objects.only('pk', 'description').iterator():
        plain = html_to_plain_text(product.description)
        if plain != product.description:
            product.description = plain
            changed.append(product)
    Product.objects.bulk_update(changed, ['description'], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ('a_shop', '0006_order_shipping_fulfilment_product_created'),
    ]

    operations = [
        migrations.RunPython(convert_descriptions, migrations.RunPython.noop),
    ]

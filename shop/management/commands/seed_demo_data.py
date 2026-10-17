from io import BytesIO

from allauth.account.models import EmailAddress
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify
from PIL import Image, ImageDraw, ImageFont

from shop.models import Category, Product, ProductImage

# (category, colour, [(name, price, stock, description, image_count)])
CATALOG = [
    ("Electronics", (37, 99, 235), [
        ("Wireless Noise-Cancelling Headphones", "129.99", 25, "Over-ear Bluetooth headphones with 30-hour battery life and active noise cancellation.", 3),
        ("Mechanical Keyboard", "89.50", 40, "Tenkeyless keyboard with hot-swappable switches and RGB backlighting.", 2),
        ("4K Action Camera", "199.00", 8, "Waterproof action camera that records 4K at 60fps with electronic stabilisation.", 1),
        ("USB-C Fast Charger 65W", "34.99", 120, "Compact GaN charger that powers laptops, tablets and phones.", 1),
    ]),
    ("Clothing", (219, 39, 119), [
        ("Classic Denim Jacket", "74.00", 30, "Mid-wash denim jacket with a relaxed fit and brass buttons.", 2),
        ("Organic Cotton T-Shirt", "19.99", 200, "Soft crew-neck tee made from 100% organic cotton.", 1),
        ("Waterproof Hiking Boots", "119.00", 3, "Leather hiking boots with a waterproof membrane and grippy soles.", 2),
        ("Wool Beanie", "15.00", 0, "Warm ribbed beanie knitted from merino wool.", 1),
    ]),
    ("Home & Kitchen", (5, 150, 105), [
        ("Pour-Over Coffee Set", "42.00", 18, "Glass dripper, carafe and 100 paper filters for a clean, bright brew.", 2),
        ("Cast Iron Skillet 12\"", "39.95", 50, "Pre-seasoned cast iron skillet for searing, baking and frying.", 1),
        ("Linen Throw Blanket", "55.00", 22, "Stone-washed linen throw that gets softer with every wash.", 1),
        ("Smart LED Desk Lamp", "48.99", 35, "Dimmable desk lamp with adjustable colour temperature and USB charging.", 2),
    ]),
    ("Books", (217, 119, 6), [
        ("The Pragmatic Programmer", "44.99", 60, "Classic guide to becoming a better, more effective software developer.", 1),
        ("Designing Data-Intensive Applications", "52.00", 14, "Deep dive into the principles behind reliable, scalable data systems.", 1),
        ("Atomic Habits", "16.99", 90, "Practical strategies for building good habits and breaking bad ones.", 1),
    ]),
    ("Sports & Outdoors", (124, 58, 237), [
        ("Yoga Mat Pro", "29.99", 75, "6mm non-slip yoga mat with alignment markings and carry strap.", 2),
        ("Insulated Water Bottle", "24.50", 150, "Stainless steel bottle that keeps drinks cold for 24 hours.", 1),
        ("Adjustable Dumbbell Pair", "159.00", 6, "Space-saving dumbbells that adjust from 2.5 to 24kg.", 2),
        ("Camping Hammock", "36.00", 0, "Lightweight parachute-nylon hammock with tree straps included.", 1),
    ]),
]

CUSTOMER_EMAIL = "customer@example.com"
CUSTOMER_PASSWORD = "Customer@12345"


def make_image(name, colour, variant):
    """Render a simple gradient placeholder with the product name."""
    width, height = 900, 900
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    shade = [max(0, c - 40 * variant) for c in colour]
    for y in range(height):
        t = y / height
        row = tuple(int(shade[i] * (1 - t) + 255 * t * 0.35 + shade[i] * t * 0.65) for i in range(3))
        draw.line([(0, y), (width, y)], fill=row)

    draw.ellipse([250, 170, 650, 570], fill=(255, 255, 255), outline=None)
    initials = "".join(word[0] for word in name.split()[:2]).upper()
    big = ImageFont.load_default(size=170)
    draw.text((450, 370), initials, font=big, fill=tuple(shade), anchor="mm")

    small = ImageFont.load_default(size=44)
    words, lines, line = name.split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=small) > 780:
            lines.append(line)
            line = word
        else:
            line = candidate
    lines.append(line)
    for i, text in enumerate(lines):
        draw.text((450, 670 + i * 56), text, font=small, fill=(255, 255, 255), anchor="mm")
    if variant:
        draw.text((450, 840), f"view {variant + 1}", font=ImageFont.load_default(size=30), fill=(255, 255, 255), anchor="mm")

    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return ContentFile(buffer.getvalue(), name=f"{slugify(name)}-{variant + 1}.jpg")


class Command(BaseCommand):
    help = "Seed categories, products with images and a test customer for local development."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete the seeded products first and recreate them.")

    @transaction.atomic
    def handle(self, *args, **options):
        names = [p[0] for _, _, products in CATALOG for p in products]
        if options["reset"]:
            deleted, _ = Product.objects.filter(name__in=names).delete()
            self.stdout.write(f"Removed {deleted} existing seeded rows.")

        created = 0
        for category_name, colour, products in CATALOG:
            category, _ = Category.objects.get_or_create(name=category_name)
            for name, price, stock, description, image_count in products:
                if Product.objects.filter(name=name).exists():
                    continue
                product = Product.objects.create(
                    name=name, price=price, stock=stock, description=description, category=category
                )
                for variant in range(image_count):
                    ProductImage.objects.create(product=product, images=make_image(name, colour, variant))
                created += 1

        Site.objects.update_or_create(id=1, defaults={"domain": "localhost:8085", "name": "Ecommerce Store"})

        customer, new_customer = User.objects.get_or_create(
            username="customer", defaults={"email": CUSTOMER_EMAIL, "first_name": "Test"}
        )
        if new_customer:
            customer.set_password(CUSTOMER_PASSWORD)
            customer.save()
        EmailAddress.objects.update_or_create(
            user=customer, email=CUSTOMER_EMAIL, defaults={"primary": True, "verified": True}
        )

        self.stdout.write(self.style.SUCCESS(
            f"Created {created} products ({Product.objects.count()} total, "
            f"{Category.objects.count()} categories). "
            f"Customer login: {CUSTOMER_EMAIL} / {CUSTOMER_PASSWORD}"
        ))

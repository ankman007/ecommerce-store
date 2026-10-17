from django.shortcuts import get_object_or_404

from shop.models import Category, Product
from shop.views.listing import render_product_listing


def category(request, slug):
    selected_category = get_object_or_404(Category, slug=slug)
    return render_product_listing(
        request,
        Product.objects.filter(category=selected_category),
        {'selected_category': selected_category.name, 'category_obj': selected_category},
    )

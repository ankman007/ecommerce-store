"""Shared product-grid listing: filtering, sorting and pagination for home, category and search."""

from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import render

from shop.forms import SORT_CHOICES, CatalogFilterForm
from shop.models import Category
from shop.utils import check_product_for_cart, product_grid_queryset

PRODUCTS_PER_PAGE = 12

# A unique tie-breaker ('id') keeps pagination stable when the sort key has duplicates.
SORT_ORDERINGS = {
    'newest': ('-created_at', '-updated_at', 'id'),
    'price_asc': ('price', 'id'),
    'price_desc': ('-price', 'id'),
    'name': ('name', 'id'),
}
DEFAULT_SORT = 'newest'


def _catalog_filters(request):
    """Validated filter values from the query string; invalid values are ignored, not errors."""
    form = CatalogFilterForm(request.GET)
    form.is_valid()
    data = getattr(form, 'cleaned_data', {})
    return {
        'sort': data.get('sort') or DEFAULT_SORT,
        'min_price': data.get('min_price'),
        'max_price': data.get('max_price'),
        'in_stock': bool(data.get('in_stock')),
    }


def filter_products(queryset, filters):
    if filters['min_price'] is not None:
        queryset = queryset.filter(price__gte=filters['min_price'])
    if filters['max_price'] is not None:
        queryset = queryset.filter(price__lte=filters['max_price'])
    if filters['in_stock']:
        queryset = queryset.filter(stock__gt=0)
    return queryset.order_by(*SORT_ORDERINGS[filters['sort']])


def render_product_listing(request, queryset, extra_context=None):
    """Render a_shop/home.html for ``queryset`` with the visitor's filters, sort and page applied.

    Queries: count + one page of products + images + categories (the footer reuses the categories).
    """
    filters = _catalog_filters(request)
    products = product_grid_queryset(filter_products(queryset, filters))
    paginator = Paginator(products, PRODUCTS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get('page'))

    categories = list(Category.objects.annotate(product_count=Count('products')).order_by('name'))
    context = {
        'products': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'is_paginated': page_obj.has_other_pages(),
        'filters': filters,
        'sort_choices': SORT_CHOICES,
        'filters_active': bool(filters['min_price'] is not None or filters['max_price'] is not None)
        or filters['in_stock'],
        'categories': categories,
        # Same rows the footer context processor would fetch; saves a query per listing page.
        'footer_categories': categories[:6],
        'cart_product_ids': check_product_for_cart(request),
    }
    context.update(extra_context or {})
    return render(request, 'a_shop/home.html', context)

from django.shortcuts import render, get_object_or_404
from shop.models import Product
from django.db.models import Q
from shop.utils import check_product_for_cart, product_grid_queryset
from shop.views.listing import render_product_listing

SIMILAR_PRODUCTS_LIMIT = 8


def product_detail(request, id):
    product = get_object_or_404(product_grid_queryset(), id=id)
    if product.category_id is not None:
        similar_products = product_grid_queryset(
            Product.objects.filter(category_id=product.category_id).exclude(id=product.id)
        )[:SIMILAR_PRODUCTS_LIMIT]
    else:
        similar_products = Product.objects.none()

    cart_product_ids = check_product_for_cart(request)
    return render(
        request,
        'a_shop/product_detail.html',
        {
            'product': product,
            'similar_products': similar_products,
            'cart_product_ids': cart_product_ids,
        },
    )


def product_search(request):
    query = request.GET.get('q', '').strip()[:200]
    if query:
        results = Product.objects.filter(Q(name__icontains=query) | Q(description__icontains=query))
    else:
        results = Product.objects.none()
    return render_product_listing(request, results, {'query': query})

from django.shortcuts import render, get_object_or_404
from shop.models import Product, Category, Cart
from django.db.models import Q
from loguru import logger
from shop.utils import check_product_for_cart

    
def product_detail(request, id):
    product = get_object_or_404(Product, id=id)
    similar_products = Product.objects.filter(category=product.category).exclude(id=product.id)
    
    cart_product_ids = check_product_for_cart(request)
    return render(request, 'a_shop/product_detail.html', {
        'product': product,
        'similar_products': similar_products,
        'cart_product_ids': cart_product_ids,  
    })


def product_search(request):
    query = request.GET.get('q', '')
    results = Product.objects.filter(Q(name__icontains=query) | Q(description__icontains=query)) if query else []
    categories = Category.objects.all()
    cart_product_ids = check_product_for_cart(request)
    return render(request, 'a_shop/home.html', {
        'query': query,
        'products': results,
        'categories': categories,
        'cart_product_ids': cart_product_ids,  
    })

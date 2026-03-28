from shop.models import Product, Category, Cart
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from shop.utils import check_product_for_cart

def category(request, slug):
    selected_category = get_object_or_404(Category, slug=slug)
    products = Product.objects.filter(category=selected_category)
    categories = Category.objects.annotate(product_count=Count('products'))
    cart_product_ids = check_product_for_cart(request)

    context = {
        'products': products,
        'categories': categories,
        'selected_category': selected_category.name,
        'cart_product_ids': cart_product_ids,  

    }
    return render(request, 'a_shop/home.html', context)
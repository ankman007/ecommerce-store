from django.contrib.sitemaps import Sitemap
from django.db.models import Max
from django.urls import reverse

from shop.models import Category, Product


class RequestHostSitemap(Sitemap):
    """Builds absolute URLs from the request host rather than the Sites framework domain,
    so the sitemap is right even if the Site record still says example.com."""

    def __init__(self, domain=None):
        self.domain = domain

    def get_domain(self, site=None):
        return self.domain or super().get_domain(site)


class StaticViewSitemap(RequestHostSitemap):
    changefreq = 'monthly'
    priority = 0.5

    def items(self):
        return ['home', 'about', 'contact', 'privacy_policy']

    def location(self, item):
        return reverse(item)


class CategorySitemap(RequestHostSitemap):
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return Category.objects.annotate(last_product_update=Max('products__updated_at')).order_by('name')

    def lastmod(self, obj):
        return obj.last_product_update


class ProductSitemap(RequestHostSitemap):
    changefreq = 'weekly'
    priority = 0.8
    limit = 5000

    def items(self):
        return Product.objects.only('id', 'updated_at').order_by('id')

    def lastmod(self, obj):
        return obj.updated_at


SITEMAP_CLASSES = {
    'static': StaticViewSitemap,
    'categories': CategorySitemap,
    'products': ProductSitemap,
}


def sitemaps_for(request):
    domain = request.get_host()
    return {name: cls(domain) for name, cls in SITEMAP_CLASSES.items()}

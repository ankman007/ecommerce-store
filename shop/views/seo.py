from django.contrib.sitemaps.views import sitemap as django_sitemap
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

from shop.sitemaps import sitemaps_for

# Pages that are private, per-user or transactional; keep crawlers out of them.
ROBOTS_DISALLOW = [
    '/admin/',
    '/accounts/',
    '/profile/',
    '/cart/',
    '/checkout/',
    '/create-checkout-session/',
    '/add-to-cart/',
    '/success/',
    '/cancel/',
    '/orders/',
    '/stripe/',
]


@require_GET
@cache_control(max_age=60 * 60)
def sitemap(request):
    return django_sitemap(request, sitemaps=sitemaps_for(request))


@require_GET
@cache_control(max_age=60 * 60 * 24)
def robots_txt(request):
    lines = ['User-agent: *']
    lines += [f'Disallow: {path}' for path in ROBOTS_DISALLOW]
    lines += ['', f"Sitemap: {request.build_absolute_uri(reverse('sitemap'))}", '']
    return HttpResponse('\n'.join(lines), content_type='text/plain; charset=utf-8')

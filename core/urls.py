from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from users.views import profile_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('a_shop.urls')),
    path('accounts/', include('allauth.urls')),
    path('profile/', include('a_users.urls')),
    path('@<username>/', profile_view, name="profile"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

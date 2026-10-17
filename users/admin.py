from django.contrib import admin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'displayname')
    search_fields = ('user__username', 'user__email', 'displayname')
    list_select_related = ('user',)
    raw_id_fields = ('user',)

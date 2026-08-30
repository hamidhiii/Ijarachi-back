from django.contrib import admin

from .models import MonitorAccess


@admin.register(MonitorAccess)
class MonitorAccessAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_active', 'can_view_deals', 'can_view_payments', 'can_manage_access', 'created_at')
    list_filter = ('is_active', 'can_manage_access')
    search_fields = ('user__phone', 'note')
    autocomplete_fields = ()
    raw_id_fields = ('user', 'created_by')

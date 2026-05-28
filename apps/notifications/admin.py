from django.contrib import admin

from .models import AuditLog, Notification, NotificationTemplate


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'type', 'is_read', 'created_at']
    list_filter = ['type', 'is_read']
    search_fields = ['user__phone']
    readonly_fields = ['payload', 'created_at']


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ['key', 'language', 'is_active', 'updated_at']
    list_filter = ['language', 'is_active']
    search_fields = ['key', 'title', 'body']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'action', 'ip_address', 'created_at']
    list_filter = ['action']
    search_fields = ['user__phone', 'action']
    readonly_fields = ['metadata', 'created_at']

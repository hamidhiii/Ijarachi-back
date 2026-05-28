from django.contrib import admin

from .models import DeliveryOrder


@admin.register(DeliveryOrder)
class DeliveryOrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking', 'direction', 'yandex_order_id', 'status', 'cost', 'created_at']
    list_filter = ['direction', 'status']
    search_fields = ['booking__id', 'yandex_order_id']
    readonly_fields = ['raw_payload', 'created_at', 'updated_at']

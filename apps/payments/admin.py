from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking', 'provider', 'amount', 'status', 'provider_transaction_id', 'created_at']
    list_filter = ['provider', 'status']
    search_fields = ['booking__id', 'provider_transaction_id']
    readonly_fields = ['raw_request', 'created_at', 'updated_at']

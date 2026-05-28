from django.contrib import admin
from .models import Payment, Transaction


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking', 'provider', 'amount', 'status', 'provider_transaction_id', 'created_at']
    list_filter = ['provider', 'status']
    search_fields = ['booking__id', 'provider_transaction_id']
    readonly_fields = ['raw_request', 'payment_url', 'created_at', 'updated_at']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'type', 'user', 'booking', 'amount', 'currency', 'created_at']
    list_filter = ['type', 'currency']
    search_fields = ['user__phone', 'booking__id', 'payment__provider_transaction_id']
    readonly_fields = ['metadata', 'created_at']

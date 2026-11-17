from django.contrib import admin
from .models import Payment, Transaction, WalletTransaction


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


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'type', 'user', 'booking', 'amount', 'balance_after', 'created_at']
    list_filter = ['type']
    search_fields = ['user__phone', 'booking__id']
    readonly_fields = ['user', 'type', 'amount', 'balance_after', 'booking', 'comment', 'created_at']

    def has_add_permission(self, request):
        # Строки пишет только credit_wallet вместе с изменением баланса.
        return False

    def has_delete_permission(self, request, obj=None):
        return False

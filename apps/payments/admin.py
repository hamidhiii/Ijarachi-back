from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking', 'provider', 'amount', 'status', 'provider_transaction_id', 'created_at']
    list_filter = ['provider', 'status']
    search_fields = ['booking__id', 'provider_transaction_id']
    readonly_fields = ['raw_request', 'created_at', 'updated_at']
    raw_id_fields = ['booking']
    
    fieldsets = (
        (None, {'fields': ('booking', 'provider', 'amount', 'status', 'provider_transaction_id')}),
        (_('Raw Data'), {'fields': ('raw_request',)}),
        (_('Timestamps'), {'fields': ('created_at', 'updated_at')}),
    )

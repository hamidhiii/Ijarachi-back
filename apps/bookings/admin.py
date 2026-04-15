from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from .models import Booking, VerificationPhoto
from apps.payments.models import Payment


class VerificationPhotoInline(admin.TabularInline):
    model = VerificationPhoto
    extra = 0
    readonly_fields = ['file_hash', 'uploaded_by', 'uploaded_at']


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ['provider', 'amount', 'status', 'provider_transaction_id', 'created_at']
    can_delete = False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['id', 'item', 'renter', 'start_date', 'end_date', 'status', 'total_price']
    list_filter = ['status', 'created_at']
    search_fields = ['item__title', 'renter__phone']
    readonly_fields = ['price_per_day', 'commission_amount', 'total_price', 'created_at', 'updated_at']
    raw_id_fields = ['item', 'renter']
    inlines = [VerificationPhotoInline, PaymentInline]
    
    fieldsets = (
        (_('Booking Details'), {'fields': ('item', 'renter', 'status')}),
        (_('Dates'), {'fields': ('start_date', 'end_date')}),
        (_('Financials'), {'fields': ('price_per_day', 'commission_amount', 'total_price')}),
        (_('Additional Info'), {'fields': ('renter_comment', 'created_at', 'updated_at')}),
    )

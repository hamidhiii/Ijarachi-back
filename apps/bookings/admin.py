from django.contrib import admin
from .models import Booking, PhotoProtocol
from apps.payments.models import Payment


class PhotoProtocolInline(admin.TabularInline):
    model = PhotoProtocol
    extra = 0
    readonly_fields = ['uploaded_by', 'uploaded_at']


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ['provider', 'amount', 'status', 'provider_transaction_id', 'created_at']
    can_delete = False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['id', 'item', 'renter', 'start_date', 'end_date', 'total_price', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['item__title', 'renter__phone']
    raw_id_fields = ['item', 'renter']
    readonly_fields = ['price_per_day', 'deposit_amount', 'commission_amount', 'total_price', 'created_at', 'updated_at']
    inlines = [PhotoProtocolInline, PaymentInline]
    fieldsets = (
        ('Сделка', {'fields': ('item', 'renter', 'status', 'renter_comment')}),
        ('Даты', {'fields': ('start_date', 'end_date')}),
        ('Финансы', {'fields': ('price_per_day', 'deposit_amount', 'commission_amount', 'total_price')}),
        ('Системное', {'fields': ('created_at', 'updated_at')}),
    )

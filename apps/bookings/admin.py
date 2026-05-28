from django.contrib import admin
from .models import Booking, Deliverer
from apps.payments.models import Payment


@admin.register(Deliverer)
class DelivererAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'phone', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'phone']


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ['provider', 'amount', 'status', 'provider_transaction_id', 'created_at']
    can_delete = False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['id', 'item', 'renter', 'start_date', 'end_date', 'delivery_method', 'total_price', 'status', 'escrow_status', 'created_at']
    list_filter = ['status', 'escrow_status', 'delivery_method']
    search_fields = ['item__title', 'renter__phone']
    raw_id_fields = ['item', 'renter', 'deliverer']
    readonly_fields = ['price_per_day', 'deposit_amount', 'commission_amount', 'total_price', 'created_at', 'updated_at']
    inlines = [PaymentInline]
    fieldsets = (
        ('Сделка', {'fields': ('item', 'renter', 'status', 'escrow_status', 'renter_comment', 'dispute_reason')}),
        ('Даты', {'fields': ('start_date', 'end_date')}),
        ('Финансы', {'fields': ('price_per_day', 'deposit_amount', 'commission_amount', 'delivery_cost', 'total_price', 'escrow_amount')}),
        ('Доставка', {'fields': ('delivery_method', 'delivery_address', 'delivery_lat', 'delivery_lng', 'delivery_comment', 'deliverer', 'pickup_eta', 'delivery_eta', 'yandex_delivery_order_id', 'yandex_delivery_status')}),
        ('Системное', {'fields': ('created_at', 'updated_at')}),
    )

from django.contrib import admin
from .models import Booking, BookingPhoto, DealReview
from apps.payments.models import Payment


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ['provider', 'amount', 'status', 'provider_transaction_id', 'created_at']
    can_delete = False


class BookingPhotoInline(admin.TabularInline):
    model = BookingPhoto
    extra = 0
    fields = ['kind', 'image', 'comment', 'uploaded_by', 'created_at']
    readonly_fields = ['created_at']
    raw_id_fields = ['uploaded_by']


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['id', 'item', 'renter', 'start_date', 'end_date', 'total_price', 'status', 'escrow_status', 'created_at']
    list_filter = ['status', 'escrow_status']
    search_fields = ['item__title', 'renter__phone']
    raw_id_fields = ['item', 'renter']
    readonly_fields = ['price_per_day', 'deposit_amount', 'commission_amount', 'total_price', 'created_at', 'updated_at']
    inlines = [PaymentInline, BookingPhotoInline]
    fieldsets = (
        ('Сделка', {'fields': ('item', 'renter', 'status', 'escrow_status', 'renter_comment', 'dispute_reason')}),
        ('Даты', {'fields': ('start_date', 'end_date')}),
        ('Финансы', {'fields': ('price_per_day', 'deposit_amount', 'commission_amount', 'total_price', 'escrow_amount')}),
        ('Системное', {'fields': ('created_at', 'updated_at')}),
    )


@admin.register(DealReview)
class DealReviewAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking', 'listing', 'reviewer', 'reviewee', 'rating', 'created_at']
    list_filter = ['rating']
    search_fields = ['listing__title', 'reviewer__phone', 'reviewee__phone', 'comment']
    raw_id_fields = ['booking', 'listing', 'reviewer', 'reviewee']

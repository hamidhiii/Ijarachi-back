from django.contrib import admin
from mptt.admin import DraggableMPTTAdmin
from .models import Category, Favorite, Item, ItemImage, ItemAvailability, Offer, PhoneReveal, Report


@admin.register(Category)
class CategoryAdmin(DraggableMPTTAdmin):
    list_display = ['tree_actions', 'indented_title', 'name_uz', 'slug', 'is_active']
    list_display_links = ['indented_title']
    list_editable = ['name_uz']
    list_filter = ['is_active']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name', 'name_uz', 'slug']


class ItemImageInline(admin.TabularInline):
    model = ItemImage
    extra = 0
    fields = ['image', 'is_primary', 'order']


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'owner', 'category', 'price_per_day', 'is_negotiable',
        'deposit', 'status', 'promotion', 'city', 'created_at',
    ]
    list_filter = ['status', 'condition', 'category', 'city', 'is_negotiable']
    search_fields = ['title', 'description', 'owner__phone']
    list_editable = ['status']
    raw_id_fields = ['owner', 'category']
    inlines = [ItemImageInline]
    readonly_fields = ['created_at', 'updated_at', 'top_until', 'vip_until']
    fieldsets = (
        ('Основное', {'fields': ('owner', 'category', 'title', 'description', 'condition', 'status')}),
        ('Цена', {'fields': ('price_per_day', 'is_negotiable', 'deposit')}),
        ('Локация', {'fields': ('city', 'address', 'latitude', 'longitude')}),
        ('Характеристики', {'fields': ('attributes',)}),
        ('Продвижение', {
            'fields': ('top_until', 'vip_until'),
            'description': 'Выдать или снять — действиями в списке объявлений или в «Тарифы → Продвижения».',
        }),
        ('Даты', {'fields': ('created_at', 'updated_at')}),
    )

    actions = ['approve', 'reject', 'deactivate', 'grant_promotion', 'stop_promotion']

    @admin.display(description='Продвижение')
    def promotion(self, obj):
        from django.utils import timezone

        now = timezone.now()
        marks = [name for name, until in (('VIP', obj.vip_until), ('топ', obj.top_until)) if until and until > now]
        return ', '.join(marks) or '—'

    @admin.action(description='Дать продвижение (топ / VIP)…')
    def grant_promotion(self, request, queryset):
        from apps.billing.admin_actions import grant_promotion_action
        return grant_promotion_action(self, request, queryset.select_related('owner'))

    @admin.action(description='Снять продвижение…')
    def stop_promotion(self, request, queryset):
        from apps.billing.admin_actions import stop_promotion_action
        return stop_promotion_action(self, request, queryset)

    def approve(self, request, queryset):
        queryset.update(status=Item.STATUS_APPROVED, rejection_reason='')
    approve.short_description = 'Одобрить выбранные объявления'

    def reject(self, request, queryset):
        queryset.update(status=Item.STATUS_REJECTED)
    reject.short_description = 'Отклонить выбранные объявления'

    def deactivate(self, request, queryset):
        queryset.update(status=Item.STATUS_INACTIVE)
    deactivate.short_description = 'Деактивировать выбранные объявления'


@admin.register(ItemAvailability)
class ItemAvailabilityAdmin(admin.ModelAdmin):
    list_display = ['item', 'blocked_count']
    search_fields = ['item__title']

    def blocked_count(self, obj):
        return len(obj.blocked_dates)
    blocked_count.short_description = 'Заблокировано дат'


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'item', 'created_at']
    search_fields = ['user__phone', 'item__title']
    raw_id_fields = ['user', 'item']


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ['id', 'item', 'renter', 'amount', 'status', 'proposed_by', 'created_at']
    list_filter = ['status', 'proposed_by']
    search_fields = ['item__title', 'renter__phone']
    raw_id_fields = ['item', 'renter']


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'item', 'reason', 'status', 'reporter', 'created_at', 'resolved_by')
    list_filter = ('status', 'reason')
    search_fields = ('item__title', 'reporter__phone', 'comment')
    readonly_fields = ('item', 'reporter', 'reason', 'comment', 'created_at')


@admin.register(PhoneReveal)
class PhoneRevealAdmin(admin.ModelAdmin):
    list_display = ('item', 'user', 'counted', 'created_at')
    list_filter = ('counted',)
    search_fields = ('item__title', 'user__phone')

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

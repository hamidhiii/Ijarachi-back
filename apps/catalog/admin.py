from django.contrib import admin
from mptt.admin import DraggableMPTTAdmin
from .models import Category, Favorite, Item, ItemImage, ItemAvailability


@admin.register(Category)
class CategoryAdmin(DraggableMPTTAdmin):
    list_display = ['tree_actions', 'indented_title', 'slug', 'is_active']
    list_display_links = ['indented_title']
    list_filter = ['is_active']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name', 'slug']


class ItemImageInline(admin.TabularInline):
    model = ItemImage
    extra = 0
    fields = ['image', 'is_primary', 'order']


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ['title', 'owner', 'category', 'price_per_day', 'deposit', 'status', 'city', 'created_at']
    list_filter = ['status', 'condition', 'category', 'city']
    search_fields = ['title', 'description', 'owner__phone']
    list_editable = ['status']
    raw_id_fields = ['owner', 'category']
    inlines = [ItemImageInline]
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Основное', {'fields': ('owner', 'category', 'title', 'description', 'condition', 'status')}),
        ('Цена', {'fields': ('price_per_day', 'deposit')}),
        ('Локация', {'fields': ('city', 'address', 'latitude', 'longitude')}),
        ('Даты', {'fields': ('created_at', 'updated_at')}),
    )

    actions = ['approve', 'reject', 'deactivate']

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

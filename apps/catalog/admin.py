from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from mptt.admin import DraggableMPTTAdmin
from .models import Category, Item, ItemImage, ItemAvailability


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
    list_display = ['title', 'category', 'owner', 'price_per_day', 'client_price_per_day', 'status', 'city']
    list_filter = ['status', 'condition', 'category', 'city']
    search_fields = ['title', 'description', 'owner__phone']
    readonly_fields = ['client_price_per_day', 'created_at', 'updated_at']
    raw_id_fields = ['owner', 'category']
    inlines = [ItemImageInline]
    
    fieldsets = (
        (_('Main Information'), {'fields': ('owner', 'category', 'title', 'description', 'condition', 'status')}),
        (_('Financials'), {'fields': ('price_per_day', 'client_price_per_day')}),
        (_('Location'), {'fields': ('address', 'city', 'latitude', 'longitude')}),
        (_('Timestamps'), {'fields': ('created_at', 'updated_at')}),
    )

    actions = ['activate', 'deactivate']

    @admin.action(description=_('Activate selected items'))
    def activate(self, request, queryset):
        queryset.update(status=Item.STATUS_ACTIVE)

    @admin.action(description=_('Deactivate selected items'))
    def deactivate(self, request, queryset):
        queryset.update(status=Item.STATUS_INACTIVE)


@admin.register(ItemAvailability)
class ItemAvailabilityAdmin(admin.ModelAdmin):
    list_display = ['item', 'blocked_count']
    search_fields = ['item__title']

    @admin.display(description=_('Blocked dates count'))
    def blocked_count(self, obj):
        return len(obj.blocked_dates)

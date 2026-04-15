from django.contrib import admin
from .models import FavoriteItem

@admin.register(FavoriteItem)
class FavoriteItemAdmin(admin.ModelAdmin):
    list_display = ['user', 'item', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__phone', 'item__title']
    raw_id_fields = ['user', 'item']

from django.contrib import admin
from .models import Review

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['id', 'reviewer', 'reviewee', 'booking', 'rating', 'created_at']
    list_filter = ['rating', 'created_at']
    search_fields = ['reviewer__phone', 'reviewee__phone']
    raw_id_fields = ['reviewer', 'reviewee', 'booking']

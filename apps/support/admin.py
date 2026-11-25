from django.contrib import admin

from .models import SupportMessage, SupportTicket


class MessageInline(admin.TabularInline):
    model = SupportMessage
    extra = 0
    fields = ('created_at', 'from_staff', 'staff_name', 'text')
    readonly_fields = ('created_at',)


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ('id', '__str__', 'source', 'status', 'updated_at')
    list_filter = ('status', 'source')
    search_fields = ('user__phone', 'phone', 'name', 'messages__text')
    raw_id_fields = ('user',)
    inlines = [MessageInline]

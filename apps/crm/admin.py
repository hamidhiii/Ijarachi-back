from django.contrib import admin

from .models import Branch, Client, Reservation, StaffMember


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'address', 'is_active')
    search_fields = ('name', 'owner__phone')


@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ('user', 'owner', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = ('user__phone', 'owner__phone')


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'owner', 'created_at')
    search_fields = ('name', 'phone', 'owner__phone')


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('item', 'quantity', 'start_date', 'end_date', 'status', 'source', 'client', 'owner')
    list_filter = ('status', 'source')
    search_fields = ('item__title', 'owner__phone', 'client__name', 'client__phone')
    date_hierarchy = 'start_date'

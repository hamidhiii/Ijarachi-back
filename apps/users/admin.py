from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Profile, OTPCode, KYCDocument, MyIDVerificationAttempt, PhoneChangeRequest


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ['phone', 'email', 'is_active', 'is_staff', 'date_joined']
    list_filter = ['is_active', 'is_staff']
    search_fields = ['phone', 'email']
    ordering = ['-date_joined']
    fieldsets = (
        (None, {'fields': ('phone', 'password')}),
        ('Personal info', {'fields': ('email',)}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('phone', 'password1', 'password2'),
        }),
    )


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'full_name', 'rating', 'verification_status', 'is_verified_myid', 'myid_verified_at']
    list_filter = ['verification_status', 'is_verified_myid']
    search_fields = ['user__phone', 'full_name']
    readonly_fields = ['myid_external_id_hash', 'myid_verified_at']


@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = ['phone', 'code', 'created_at', 'is_used']
    list_filter = ['is_used']
    search_fields = ['phone']
    ordering = ['-created_at']


@admin.register(KYCDocument)
class KYCDocumentAdmin(admin.ModelAdmin):
    list_display = ['user', 'status', 'submitted_at', 'reviewed_at']
    list_filter = ['status']
    search_fields = ['user__phone']
    actions = ['approve', 'reject']

    def approve(self, request, queryset):
        from django.utils import timezone
        from .models import Profile
        queryset.update(status=KYCDocument.STATUS_APPROVED, reviewed_at=timezone.now())
        for kyc in queryset:
            Profile.objects.filter(user=kyc.user).update(
                verification_status=Profile.VERIFICATION_VERIFIED
            )
    approve.short_description = 'Одобрить выбранные KYC'

    def reject(self, request, queryset):
        from django.utils import timezone
        queryset.update(status=KYCDocument.STATUS_REJECTED, reviewed_at=timezone.now())
    reject.short_description = 'Отклонить выбранные KYC'


@admin.register(MyIDVerificationAttempt)
class MyIDVerificationAttemptAdmin(admin.ModelAdmin):
    list_display = ['user', 'state', 'status', 'created_at', 'finished_at']
    list_filter = ['status']
    search_fields = ['user__phone', 'state']
    readonly_fields = ['state', 'status', 'error', 'created_at', 'finished_at']


@admin.register(PhoneChangeRequest)
class PhoneChangeRequestAdmin(admin.ModelAdmin):
    list_display = ['user', 'new_phone', 'created_at', 'is_used']
    list_filter = ['is_used']
    search_fields = ['user__phone', 'new_phone']

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from .models import CustomUser, Profile, OTPCode, KYCDocument


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ['email', 'phone', 'is_active', 'is_staff', 'date_joined']
    list_filter = ['is_active', 'is_staff']
    search_fields = ['email', 'phone']
    ordering = ['-date_joined']
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal Info'), {'fields': ('phone',)}),
        (_('Permissions'), {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        (_('Important Dates'), {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2'),
        }),
    )


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'full_name', 'rating', 'verification_status', 'language']
    list_filter = ['verification_status', 'language']
    search_fields = ['user__email', 'full_name']
    readonly_fields = ['rating', 'rating_count']
    fieldsets = (
        (None, {'fields': ('user', 'full_name', 'avatar')}),
        (_('Rating & Stats'), {'fields': ('rating', 'rating_count')}),
        (_('Verification'), {'fields': ('verification_status',)}),
        (_('App Settings'), {'fields': ('fcm_token', 'language')}),
    )


@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = ['email', 'code', 'created_at', 'is_used']
    list_filter = ['is_used']
    search_fields = ['email']
    ordering = ['-created_at']


@admin.register(KYCDocument)
class KYCDocumentAdmin(admin.ModelAdmin):
    list_display = ['user', 'status', 'submitted_at', 'reviewed_at']
    list_filter = ['status']
    search_fields = ['user__email']
    actions = ['approve', 'reject']

    @admin.action(description=_('Approve selected KYC documents'))
    def approve(self, request, queryset):
        from django.utils import timezone
        from .models import Profile
        queryset.update(status=KYCDocument.STATUS_APPROVED, reviewed_at=timezone.now())
        for kyc in queryset:
            Profile.objects.filter(user=kyc.user).update(
                verification_status=Profile.VERIFICATION_VERIFIED
            )

    @admin.action(description=_('Reject selected KYC documents'))
    def reject(self, request, queryset):
        from django.utils import timezone
        queryset.update(status=KYCDocument.STATUS_REJECTED, reviewed_at=timezone.now())

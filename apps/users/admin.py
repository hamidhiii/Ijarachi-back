from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    CustomUser, Profile, OTPCode, KYCDocument,
    PassportDocument, FaceVerification, PhoneChangeRequest, TelegramLink,
)


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
    list_display = ['user', 'full_name', 'rating', 'verification_status', 'is_verified_kyc', 'kyc_verified_at']
    list_filter = ['verification_status', 'is_verified_kyc']
    search_fields = ['user__phone', 'full_name']
    readonly_fields = ['kyc_verified_at']


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


@admin.register(PassportDocument)
class PassportDocumentAdmin(admin.ModelAdmin):
    list_display = ['user', 'document_type', 'series', 'number', 'status', 'submitted_at', 'verified_at']
    list_filter = ['status', 'document_type']
    search_fields = ['user__phone', 'series', 'number', 'pinfl', 'full_name']
    readonly_fields = ['face_encoding', 'raw_ocr_text', 'submitted_at', 'verified_at']
    actions = ['approve', 'reject']

    def approve(self, request, queryset):
        for doc in queryset:
            doc.mark_verified()
    approve.short_description = 'Подтвердить выбранные документы'

    def reject(self, request, queryset):
        for doc in queryset:
            doc.mark_rejected('Отклонено администратором')
    reject.short_description = 'Отклонить выбранные документы'


@admin.register(FaceVerification)
class FaceVerificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'status', 'face_match_score', 'liveness_score', 'submitted_at', 'verified_at']
    list_filter = ['status']
    search_fields = ['user__phone']
    readonly_fields = [
        'face_match_score', 'face_match_passed', 'liveness_score', 'liveness_passed',
        'submitted_at', 'verified_at',
    ]


@admin.register(PhoneChangeRequest)
class PhoneChangeRequestAdmin(admin.ModelAdmin):
    list_display = ['user', 'new_phone', 'created_at', 'is_used']
    list_filter = ['is_used']
    search_fields = ['user__phone', 'new_phone']


@admin.register(TelegramLink)
class TelegramLinkAdmin(admin.ModelAdmin):
    list_display = ['phone', 'chat_id', 'username', 'linked_at', 'updated_at']
    search_fields = ['phone', 'username']

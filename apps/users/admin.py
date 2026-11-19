from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    CustomUser, Profile, OTPCode, KYCDocument,
    PassportDocument, FaceVerification, PhoneChangeRequest, TelegramLink,
)


class PlanFilter(admin.SimpleListFilter):
    title = 'Тариф'
    parameter_name = 'plan'

    def lookups(self, request, model_admin):
        from apps.billing.models import Plan
        return [(p.code, p.name) for p in Plan.objects.order_by('rank')]

    def queryset(self, request, queryset):
        from django.utils import timezone
        from apps.billing.models import Plan

        if not self.value():
            return queryset
        active = {'subscription__ends_at__gt': timezone.now()}
        if self.value() == Plan.FREE:
            return queryset.exclude(**active)
        return queryset.filter(subscription__plan__code=self.value(), **active)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ['phone', 'email', 'plan_now', 'is_active', 'is_staff', 'date_joined']
    list_filter = [PlanFilter, 'is_active', 'is_staff']
    search_fields = ['phone', 'email', 'profile__full_name', 'profile__shop_name']
    ordering = ['-date_joined']
    list_select_related = ['subscription__plan']
    readonly_fields = ['plan_now', 'plan_history']
    actions = ['grant_plan', 'finish_plan']
    fieldsets = (
        (None, {'fields': ('phone', 'password')}),
        ('Personal info', {'fields': ('email',)}),
        ('Тариф', {
            'fields': ('plan_now', 'plan_history'),
            'description': 'Сменить тариф — «Тариф сейчас» → страница подписки, '
                           'или в списке пользователей действие «Выдать / сменить тариф».',
        }),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    @admin.display(description='Тариф сейчас')
    def plan_now(self, user):
        from django.urls import reverse
        from django.utils import timezone
        from django.utils.html import format_html

        subscription = getattr(user, 'subscription', None)
        if subscription is None or subscription.ends_at <= timezone.now():
            url = reverse('admin:billing_subscription_add') + f'?user={user.pk}'
            return format_html('FREE · <a href="{}">выдать тариф</a>', url)
        url = reverse('admin:billing_subscription_change', args=[subscription.pk])
        until = timezone.localtime(subscription.ends_at).strftime('%d.%m.%Y')
        return format_html('<a href="{}">{} до {}</a>', url, subscription.plan.name, until)

    @admin.display(description='История тарифа')
    def plan_history(self, user):
        from apps.billing.admin import history_table
        return history_table(user) if user.pk else '—'

    @admin.action(description='Выдать / сменить тариф…')
    def grant_plan(self, request, queryset):
        from apps.billing.admin_actions import grant_plan_action
        return grant_plan_action(self, request, queryset)

    @admin.action(description='Завершить тариф сейчас (перевести на FREE)')
    def finish_plan(self, request, queryset):
        from apps.billing.admin_actions import finish_plan_action
        return finish_plan_action(self, request, queryset)
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('phone', 'password1', 'password2'),
        }),
    )


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'full_name', 'account_type', 'shop_name', 'rating', 'verification_status', 'is_verified_kyc', 'kyc_verified_at']
    list_filter = ['account_type', 'verification_status', 'is_verified_kyc']
    search_fields = ['user__phone', 'full_name', 'shop_name']
    # Баланс меняется только через apps.payments.wallet.credit_wallet (с записью в журнал).
    readonly_fields = ['kyc_verified_at', 'wallet_balance']


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
            profile, _ = Profile.objects.get_or_create(user=kyc.user)
            # mark_kyc_verified ставит флаг, дату и статус разом. Прежний
            # bulk-update менял только статус, и профиль оказывался проверенным
            # без даты проверки — а флаг is_verified_kyc вовсе не поднимался.
            profile.mark_kyc_verified()
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

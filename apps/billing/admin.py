from django.contrib import admin, messages

from .models import BillingOrder, Plan, Promotion, Subscription, SubscriptionPeriod


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'price', 'listing_limit', 'crm', 'search_priority', 'staff_access',
                    'statistics', 'branches', 'data_export', 'is_active')
    list_editable = ('price', 'listing_limit', 'is_active')
    readonly_fields = ('code',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PeriodInline(admin.TabularInline):
    model = SubscriptionPeriod
    fk_name = 'user'
    extra = 0
    can_delete = False
    fields = ('plan', 'starts_at', 'ends_at', 'source', 'amount', 'created_by', 'comment')
    readonly_fields = fields


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'ends_at', 'created_at')
    list_filter = ('plan',)
    search_fields = ('user__phone',)
    readonly_fields = ('user', 'plan', 'ends_at', 'created_at', 'updated_at')
    # Менять тариф — только действием «продлить» (здесь или admin-api
    # /admin-api/billing/subscriptions/extend/), чтобы каждое изменение
    # попадало в историю периодов.
    actions = ['extend_one_period']

    @admin.action(description='Продлить тот же тариф на период (вручную)')
    def extend_one_period(self, request, queryset):
        from .services import extend_subscription, restore_paused_listings
        from .models import SubscriptionPeriod

        for subscription in queryset.select_related('plan', 'user'):
            extend_subscription(
                subscription.user, subscription.plan, source=SubscriptionPeriod.SOURCE_MANUAL,
                created_by=request.user, comment='Продлено в админке', replace_active=True,
            )
            restore_paused_listings(subscription.user)
        self.message_user(request, f'Продлено подписок: {queryset.count()}', messages.SUCCESS)

    def has_add_permission(self, request):
        return False


@admin.register(SubscriptionPeriod)
class SubscriptionPeriodAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'starts_at', 'ends_at', 'source', 'amount', 'created_by')
    list_filter = ('plan', 'source')
    search_fields = ('user__phone',)

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


@admin.register(BillingOrder)
class BillingOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'kind', 'plan', 'promotion', 'item', 'amount', 'provider', 'status',
                    'needs_attention', 'created_at', 'paid_at')
    list_filter = ('status', 'kind', 'provider')
    search_fields = ('user__phone', 'provider_transaction_id')

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ('item', 'kind', 'starts_at', 'ends_at', 'order')
    list_filter = ('kind',)
    search_fields = ('item__title', 'item__owner__phone')

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

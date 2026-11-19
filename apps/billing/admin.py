from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from . import admin_actions as act
from .models import BillingOrder, Plan, Promotion, Subscription, SubscriptionPeriod


def money(value):
    return f'{int(value or 0):,}'.replace(',', ' ')


def history_table(user):
    """История тарифа пользователя — таблица для страниц подписки и пользователя."""
    periods = SubscriptionPeriod.objects.filter(user=user).select_related('plan', 'created_by').order_by('-starts_at')[:50]
    if not periods:
        return 'Платных периодов не было.'
    rows = format_html_join('', '<tr><td>{}</td><td>{} — {}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>', (
        (p.plan.name, timezone.localtime(p.starts_at).strftime('%d.%m.%Y %H:%M'),
         timezone.localtime(p.ends_at).strftime('%d.%m.%Y %H:%M'), p.get_source_display(), money(p.amount),
         p.created_by or '—', p.comment or '')
        for p in periods
    ))
    return format_html(
        '<table><thead><tr><th>Тариф</th><th>Период</th><th>Источник</th><th>Сумма</th><th>Кто</th>'
        '<th>Комментарий</th></tr></thead><tbody>{}</tbody></table>', rows,
    )


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    """Цены, лимиты и права тарифов. Набор тарифов (коды) задан в коде — добавлять и удалять нельзя."""
    list_display = ('name', 'code', 'price', 'listing_limit', 'crm', 'search_priority', 'staff_access',
                    'statistics', 'branches', 'data_export', 'is_active', 'subscribers')
    list_editable = ('price', 'listing_limit', 'crm', 'search_priority', 'staff_access',
                     'statistics', 'branches', 'data_export', 'is_active')
    readonly_fields = ('code',)
    fieldsets = (
        (None, {'fields': ('code', 'name', 'price', 'listing_limit', 'rank', 'is_active')}),
        ('Что даёт тариф', {'fields': ('crm', 'search_priority', 'staff_access', 'statistics',
                                       'branches', 'data_export')}),
    )

    @admin.display(description='Сейчас на тарифе')
    def subscribers(self, plan):
        if not plan.is_paid:
            return '—'
        count = plan.subscriptions.filter(ends_at__gt=timezone.now()).count()
        url = reverse('admin:billing_subscription_changelist') + f'?plan__id__exact={plan.pk}&state=active'
        return format_html('<a href="{}">{}</a>', url, count)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class StateFilter(admin.SimpleListFilter):
    title = 'Состояние'
    parameter_name = 'state'

    def lookups(self, request, model_admin):
        return [('active', 'Действует'), ('week', 'Заканчивается за 7 дней'), ('expired', 'Закончился')]

    def queryset(self, request, queryset):
        now = timezone.now()
        if self.value() == 'active':
            return queryset.filter(ends_at__gt=now)
        if self.value() == 'week':
            return queryset.filter(ends_at__gt=now, ends_at__lte=now + timedelta(days=7))
        if self.value() == 'expired':
            return queryset.filter(ends_at__lte=now)
        return queryset


class SubscriptionForm(forms.ModelForm):
    """
    Новая подписка — пользователь + тариф. У существующей поля тарифа
    необязательны: пусто — ничего не меняется. Сохраняет не форма, а
    extend_subscription / end_subscription (SubscriptionAdmin.save_model),
    так что каждое изменение попадает в историю.
    """
    new_plan = act.PlanChoiceField(Plan.objects.order_by('rank'), label='Тариф', required=False,
                               help_text='FREE — завершить платный тариф сейчас.')
    days = forms.IntegerField(label='Срок, дней', min_value=1, max_value=3650, required=False,
                              initial=act.period_days,
                              help_text='Тот же тариф продлевается от конца текущего периода, другой включается сразу.')
    amount = forms.DecimalField(label='Получено, сум', min_value=0, decimal_places=0, required=False, initial=0,
                                help_text='Если оплатили наличными или переводом.')
    comment = forms.CharField(label='Комментарий', max_length=200, required=False)
    notify = forms.BooleanField(label='Уведомить пользователя', required=False, initial=True)

    class Meta:
        model = Subscription
        fields = ('user',)

    def validate_unique(self):
        # У пользователя уже есть строка подписки — это нормально: её продлит сервис.
        pass

    def clean(self):
        data = super().clean()
        if self.instance.pk is None and not data.get('new_plan'):
            self.add_error('new_plan', 'Выберите тариф.')
        if data.get('new_plan') and data['new_plan'].is_paid and not data.get('days'):
            self.add_error('days', 'Укажите срок.')
        return data


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    form = SubscriptionForm
    list_display = ('user', 'plan', 'ends_at', 'state', 'paid_total', 'updated_at')
    list_filter = (StateFilter, 'plan')
    search_fields = ('user__phone', 'user__profile__full_name', 'user__profile__shop_name')
    list_select_related = ('user', 'plan')
    raw_id_fields = ('user',)
    actions = ['change_plan', 'extend_one_period', 'finish_now']

    CHANGE_FIELDS = ('new_plan', 'days', 'amount', 'comment', 'notify')

    def get_readonly_fields(self, request, obj=None):
        return ('user', 'current_plan', 'ends_at', 'state', 'history') if obj else ()

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return ((None, {'fields': ('user', *self.CHANGE_FIELDS)}),)
        return (
            ('Сейчас', {'fields': ('user', 'current_plan', 'ends_at', 'state')}),
            ('Выдать, продлить или сменить тариф', {
                'fields': self.CHANGE_FIELDS,
                'description': 'Оставьте «Тариф» пустым, чтобы ничего не менять.',
            }),
            ('История', {'fields': ('history',)}),
        )

    @admin.display(description='Тариф сейчас')
    def current_plan(self, obj):
        return obj.plan.name if obj.ends_at > timezone.now() else f'FREE (был {obj.plan.name})'

    @admin.display(description='Состояние')
    def state(self, obj):
        if obj.ends_at <= timezone.now():
            return 'закончился'
        return f'действует, ещё {(obj.ends_at - timezone.now()).days} дн.'

    @admin.display(description='Оплачено всего, сум')
    def paid_total(self, obj):
        return money(sum(SubscriptionPeriod.objects.filter(user=obj.user_id).values_list('amount', flat=True)))

    @admin.display(description='Периоды')
    def history(self, obj):
        return history_table(obj.user)

    def save_model(self, request, obj, form, change):
        data = form.cleaned_data
        plan = data.get('new_plan')
        if not plan:
            return  # открыли и сохранили без изменений
        with transaction.atomic():
            act.apply_plan(obj.user, plan=plan, days=data.get('days'), amount=data.get('amount'),
                           comment=data.get('comment', ''), notify=data.get('notify'), staff=request.user)
        saved = Subscription.objects.filter(user=obj.user).first()
        if saved is not None:
            obj.pk, obj.plan, obj.ends_at = saved.pk, saved.plan, saved.ends_at
            obj._state.adding = False

    def response_add(self, request, obj, post_url_continue=None):
        if obj.pk is None:
            # FREE пользователю без подписки: завершать нечего.
            self.message_user(request, 'У пользователя не было платного тарифа — ничего не изменено.', messages.WARNING)
            return self.response_post_save_add(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def log_addition(self, request, obj, message):
        if obj.pk:
            return super().log_addition(request, obj, message)

    @admin.action(description='Выдать / сменить тариф…')
    def change_plan(self, request, queryset):
        return act.grant_plan_action(self, request, queryset.select_related('user'), user_of=lambda s: s.user)

    @admin.action(description='Продлить тот же тариф на период')
    def extend_one_period(self, request, queryset):
        extended = 0
        for subscription in queryset.select_related('plan', 'user'):
            with transaction.atomic():
                act.apply_plan(subscription.user, plan=subscription.plan, days=act.period_days(),
                               comment='Продлено в админке', staff=request.user)
            extended += 1
        self.message_user(request, f'Продлено подписок: {extended}', messages.SUCCESS)

    @admin.action(description='Завершить тариф сейчас (перевести на FREE)')
    def finish_now(self, request, queryset):
        return act.finish_plan_action(self, request, queryset.select_related('user'), user_of=lambda s: s.user)

    def has_delete_permission(self, request, obj=None):
        # Завершайте действием «Завершить тариф сейчас» — так остаётся история.
        return False


@admin.register(SubscriptionPeriod)
class SubscriptionPeriodAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'starts_at', 'ends_at', 'source', 'amount', 'created_by', 'comment')
    list_filter = ('plan', 'source')
    search_fields = ('user__phone', 'comment')
    list_select_related = ('user', 'plan', 'created_by')
    date_hierarchy = 'starts_at'

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AttentionFilter(admin.SimpleListFilter):
    title = 'Требует внимания'
    parameter_name = 'attention'

    def lookups(self, request, model_admin):
        return [('yes', 'Да'), ('no', 'Нет')]

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.exclude(needs_attention='')
        if self.value() == 'no':
            return queryset.filter(needs_attention='')
        return queryset


@admin.register(BillingOrder)
class BillingOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'kind', 'plan', 'promotion', 'item', 'amount', 'provider', 'status',
                    'needs_attention', 'created_at', 'paid_at')
    list_filter = ('status', 'kind', 'provider', AttentionFilter)
    search_fields = ('id', 'user__phone', 'provider_transaction_id')
    list_select_related = ('user', 'plan', 'item')
    date_hierarchy = 'created_at'
    actions = ['mark_paid', 'cancel_pending', 'apply_plan_again', 'clear_attention']

    @admin.action(description='Отметить оплаченным (деньги получены вне Click/Payme)')
    def mark_paid(self, request, queryset):
        from .services import mark_order_paid

        paid = 0
        for order in queryset.filter(status=BillingOrder.STATUS_PENDING):
            with transaction.atomic():
                BillingOrder.objects.filter(pk=order.pk).update(raw={
                    **order.raw, 'manual_paid_by': str(request.user), 'manual_paid_at': timezone.now().isoformat(),
                })
                mark_order_paid(order.pk)
            paid += 1
        self.message_user(request, f'Оплачено вручную: {paid} (учитываются только «Ждёт оплаты»).', messages.SUCCESS)

    @admin.action(description='Отменить (только «Ждёт оплаты»)')
    def cancel_pending(self, request, queryset):
        count = queryset.filter(status=BillingOrder.STATUS_PENDING).update(status=BillingOrder.STATUS_CANCELLED)
        self.message_user(request, f'Отменено: {count}.', messages.SUCCESS)

    @admin.action(description='Применить тариф оплаченного заказа и снять пометку')
    def apply_plan_again(self, request, queryset):
        applied = 0
        orders = queryset.filter(status=BillingOrder.STATUS_PAID, kind=BillingOrder.KIND_PLAN).exclude(needs_attention='')
        for order in orders.select_related('user', 'plan'):
            with transaction.atomic():
                act.apply_plan(order.user, plan=order.plan, days=act.period_days(), amount=order.amount,
                               comment=f'Заказ #{order.pk}, применён в админке', staff=request.user)
                BillingOrder.objects.filter(pk=order.pk).update(needs_attention='')
            applied += 1
        self.message_user(request, f'Применено: {applied} (только оплаченные тарифы с пометкой).', messages.SUCCESS)

    @admin.action(description='Снять пометку «требует внимания»')
    def clear_attention(self, request, queryset):
        count = queryset.exclude(needs_attention='').update(needs_attention='')
        self.message_user(request, f'Пометка снята: {count}.', messages.SUCCESS)

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PromotionAddForm(forms.ModelForm):
    days = forms.IntegerField(label='Срок, дней', min_value=1, max_value=365, initial=7,
                              help_text='Добавляется к текущему сроку, если продвижение уже действует.')
    notify = forms.BooleanField(label='Уведомить владельца', required=False, initial=True)

    class Meta:
        model = Promotion
        fields = ('item', 'kind')


class PromotionStateFilter(admin.SimpleListFilter):
    title = 'Состояние'
    parameter_name = 'state'

    def lookups(self, request, model_admin):
        return [('active', 'Действует'), ('expired', 'Закончилось')]

    def queryset(self, request, queryset):
        if self.value() == 'active':
            return queryset.filter(ends_at__gt=timezone.now())
        if self.value() == 'expired':
            return queryset.filter(ends_at__lte=timezone.now())
        return queryset


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ('item', 'kind', 'starts_at', 'ends_at', 'source', 'order')
    list_filter = (PromotionStateFilter, 'kind')
    search_fields = ('item__title', 'item__owner__phone')
    list_select_related = ('item', 'order')
    raw_id_fields = ('item',)
    actions = ['stop_now']

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs['form'] = PromotionAddForm
            kwargs['fields'] = ('item', 'kind', 'days', 'notify')
        return super().get_form(request, obj, **kwargs)

    def get_fields(self, request, obj=None):
        return ('item', 'kind', 'days', 'notify') if obj is None else ('item', 'kind', 'starts_at', 'ends_at', 'order')

    def get_readonly_fields(self, request, obj=None):
        return () if obj is None else ('item', 'kind', 'starts_at', 'ends_at', 'order')

    @admin.display(description='Источник')
    def source(self, obj):
        return 'оплата' if obj.order_id else 'вручную'

    def save_model(self, request, obj, form, change):
        data = form.cleaned_data
        with transaction.atomic():
            act.apply_promotion(data['item'], kind=data['kind'], days=data['days'], notify=data.get('notify'))
        created = Promotion.objects.filter(item=data['item'], kind=data['kind']).order_by('-pk').first()
        obj.pk, obj.starts_at, obj.ends_at = created.pk, created.starts_at, created.ends_at
        obj._state.adding = False

    @admin.action(description='Остановить продвижение сейчас')
    def stop_now(self, request, queryset):
        stopped = 0
        for promotion in queryset.filter(ends_at__gt=timezone.now()).select_related('item'):
            with transaction.atomic():
                stopped += act.stop_promotions(promotion.item, promotion.kind)
        self.message_user(request, f'Остановлено: {stopped}.', messages.SUCCESS)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

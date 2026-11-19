"""
Управление тарифами и продвижением из Django-админки.

Все изменения идут через те же сервисы, что и оплата (extend_subscription,
end_subscription, extend_promotion), поэтому каждое попадает в историю периодов
с источником «вручную» и автором. Действия с формой (тариф, срок, комментарий)
показывают промежуточную страницу admin/billing/action_form.html.
"""
from django import forms
from django.contrib import messages
from django.contrib.admin import helpers
from django.db import transaction
from django.template.response import TemplateResponse
from django.utils import timezone

from .models import BillingOrder, Plan, SubscriptionPeriod
from .services import end_subscription, extend_subscription, period_days, restore_paused_listings, _notify


# ─── Формы ───────────────────────────────────────────────────────────────────

class PlanChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, plan):
        price = f'{int(plan.price):,}'.replace(',', ' ')
        return f'{plan.name} — {price} сум/мес' if plan.is_paid else f'{plan.name} — завершить платный тариф'


class GrantPlanForm(forms.Form):
    plan = PlanChoiceField(Plan.objects.order_by('rank'), label='Тариф', empty_label=None)
    days = forms.IntegerField(
        label='Срок, дней', min_value=1, max_value=3650, initial=period_days,
        help_text='Тот же тариф продлевается от конца текущего периода, другой включается сразу.',
    )
    amount = forms.DecimalField(
        label='Получено, сум', min_value=0, decimal_places=0, required=False, initial=0,
        help_text='Если оплатили наличными или переводом — попадёт в историю периода.',
    )
    comment = forms.CharField(label='Комментарий', max_length=200, required=False)
    notify = forms.BooleanField(label='Уведомить пользователя', required=False, initial=True)


class PromotionForm(forms.Form):
    kind = forms.ChoiceField(label='Продвижение', choices=BillingOrder.PROMO_CHOICES)
    days = forms.IntegerField(label='Срок, дней', min_value=1, max_value=365, initial=7,
                              help_text='Добавляется к текущему сроку, если продвижение уже действует.')
    notify = forms.BooleanField(label='Уведомить владельца', required=False, initial=True)


class StopPromotionForm(forms.Form):
    kind = forms.ChoiceField(label='Что снять', choices=[('all', 'Всё продвижение'), *BillingOrder.PROMO_CHOICES])


# ─── Применение ──────────────────────────────────────────────────────────────

def apply_plan(user, *, plan, days, staff, amount=0, comment='', notify=True):
    """Выдать, продлить или сменить тариф. FREE — завершить платный тариф сейчас."""
    if not plan.is_paid:
        return finish_plan(user, staff=staff, comment=comment, notify=notify)
    subscription = extend_subscription(
        user, plan, days=days, source=SubscriptionPeriod.SOURCE_MANUAL, amount=amount or 0,
        created_by=staff, comment=comment or 'Выдан в админке', replace_active=True,
    )
    restore_paused_listings(user)
    if notify:
        _notify(user, 'Тариф подключён',
                f'Тариф {plan.name} действует до {timezone.localtime(subscription.ends_at):%d.%m.%Y %H:%M}.')
    return True


def finish_plan(user, *, staff, comment='', notify=True):
    """Завершить тариф сейчас; объявления сверх лимита FREE снимаются после коммита."""
    from .tasks import expire_one

    subscription = end_subscription(user, created_by=staff, comment=comment)
    if subscription is None:
        return False
    if notify:
        transaction.on_commit(lambda: expire_one(subscription.pk))
    else:
        # Без уведомления: только снять лишние объявления.
        from .plans import free_plan
        from .services import pause_listings_over_limit

        pause_listings_over_limit(user, free_plan())
        subscription.expiry_processed_for = subscription.ends_at
        subscription.save(update_fields=['expiry_processed_for', 'updated_at'])
    return True


def apply_promotion(item, *, kind, days, notify=True):
    from .promotions import extend_promotion

    item, ends_at = extend_promotion(item.pk, kind, days)
    if notify:
        _notify(item.owner, 'Продвижение подключено',
                f'{dict(BillingOrder.PROMO_CHOICES)[kind]} для «{item.title}» действует до '
                f'{timezone.localtime(ends_at):%d.%m.%Y %H:%M}.')
    return True


def stop_promotions(item, kind):
    from .promotions import stop_promotion

    kinds = [k for k, _ in BillingOrder.PROMO_CHOICES] if kind == 'all' else [kind]
    return any([stop_promotion(item.pk, k) for k in kinds])


# ─── Действие с промежуточной формой ────────────────────────────────────────

def form_action(modeladmin, request, queryset, *, form_class, title, apply, done, note=''):
    """
    Первый заход — страница с формой; «Применить» — apply(obj, data) для каждой
    строки, затем возврат к списку с сообщением done(count).
    """
    if 'apply' in request.POST:
        form = form_class(request.POST)
        if form.is_valid():
            changed = 0
            for obj in queryset:
                with transaction.atomic():
                    changed += bool(apply(obj, form.cleaned_data))
            modeladmin.message_user(request, done(changed), messages.SUCCESS)
            return None
    else:
        form = form_class()
    return TemplateResponse(request, 'admin/billing/action_form.html', {
        **modeladmin.admin_site.each_context(request),
        'title': title,
        'note': note,
        'form': form,
        'objects': list(queryset),
        'opts': modeladmin.model._meta,
        'action': request.POST.get('action', ''),
        'select_across': request.POST.get('select_across', '0'),
        'selected': request.POST.getlist(helpers.ACTION_CHECKBOX_NAME),
    })


def grant_plan_action(modeladmin, request, queryset, user_of=lambda obj: obj):
    return form_action(
        modeladmin, request, queryset, form_class=GrantPlanForm,
        title='Выдать или сменить тариф',
        note='Выбор FREE завершает платный тариф сейчас: лишние объявления уйдут в неактивные (не удаляются).',
        apply=lambda obj, data: apply_plan(
            user_of(obj), plan=data['plan'], days=data['days'], amount=data.get('amount'),
            comment=data.get('comment', ''), notify=data.get('notify'), staff=request.user,
        ),
        done=lambda n: f'Тариф изменён у {n}.',
    )


def finish_plan_action(modeladmin, request, queryset, user_of=lambda obj: obj):
    finished = 0
    for obj in queryset:
        with transaction.atomic():
            finished += finish_plan(user_of(obj), staff=request.user, comment='Завершён в админке')
    level = messages.SUCCESS if finished else messages.WARNING
    modeladmin.message_user(request, f'Тариф завершён у {finished} (у остальных платного тарифа не было).', level)


def grant_promotion_action(modeladmin, request, queryset, item_of=lambda obj: obj):
    return form_action(
        modeladmin, request, queryset, form_class=PromotionForm, title='Дать продвижение',
        apply=lambda obj, data: apply_promotion(item_of(obj), kind=data['kind'], days=data['days'],
                                                notify=data.get('notify')),
        done=lambda n: f'Продвижение выдано: {n}.',
    )


def stop_promotion_action(modeladmin, request, queryset, item_of=lambda obj: obj):
    return form_action(
        modeladmin, request, queryset, form_class=StopPromotionForm, title='Снять продвижение',
        apply=lambda obj, data: stop_promotions(item_of(obj), data['kind']),
        done=lambda n: f'Продвижение снято: {n}.',
    )

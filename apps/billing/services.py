"""
Изменение тарифа пользователя — только через extend_subscription: и после
оплаты, и при ручном продлении сотрудником.

Правила (решение 16.11.2026, оплата — разовым платежом за месяц, продление вручную):
- тот же тариф, пока он действует — новый период начинается с конца текущего;
- тариф выше — начинается сразу, остаток прежнего не переносится;
- тариф ниже, пока текущий действует, — отказ (дождаться окончания); сотрудник
  может выдать его сразу (`replace_active=True`);
- тариф закончился — новый начинается с момента оплаты.
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException

from .models import Plan, Subscription, SubscriptionPeriod


class BillingError(APIException):
    """400 {code, detail}: код остаётся строкой (ValidationError превратил бы его в список)."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'BILLING_ERROR'

    def __init__(self, code, detail):
        super().__init__()
        self.detail = {'code': code, 'detail': detail}


def period_days():
    return settings.BILLING_PERIOD_DAYS


def check_can_buy(user, plan):
    """400 с кодом, если этот тариф сейчас купить нельзя."""
    if not plan.is_paid or not plan.is_active:
        raise BillingError('PLAN_NOT_FOR_SALE', 'Этот тариф нельзя купить.')
    current = Subscription.objects.select_related('plan').filter(user=user, ends_at__gt=timezone.now()).first()
    if current and plan.rank < current.plan.rank:
        raise BillingError(
            'PLAN_DOWNGRADE_WHILE_ACTIVE',
            f'Тариф {current.plan.name} действует до {timezone.localtime(current.ends_at):%d.%m.%Y}. '
            'Перейти на тариф ниже можно после его окончания.',
        )


@transaction.atomic
def extend_subscription(user, plan: Plan, *, days=None, source=SubscriptionPeriod.SOURCE_PAYMENT,
                        amount=0, created_by=None, comment='', replace_active=False):
    days = days or period_days()
    now = timezone.now()
    subscription = Subscription.objects.select_for_update().select_related('plan').filter(user=user).first()
    active = subscription is not None and subscription.ends_at > now

    if active and subscription.plan_id == plan.pk:
        starts_at = subscription.ends_at
    elif active and plan.rank < subscription.plan.rank and not replace_active:
        raise BillingError('PLAN_DOWNGRADE_WHILE_ACTIVE', 'Текущий тариф ещё действует.')
    else:
        starts_at = now
        if active:
            # Прежний тариф заменён сейчас: в истории его период заканчивается здесь.
            SubscriptionPeriod.objects.filter(user=user, ends_at__gt=now).update(ends_at=now)
    ends_at = starts_at + timedelta(days=days)

    if subscription is None:
        subscription = Subscription.objects.create(user=user, plan=plan, ends_at=ends_at)
    else:
        subscription.plan = plan
        subscription.ends_at = ends_at
        subscription.save(update_fields=['plan', 'ends_at', 'updated_at'])

    SubscriptionPeriod.objects.create(
        user=user, plan=plan, starts_at=starts_at, ends_at=ends_at, source=source,
        amount=amount, created_by=created_by, comment=comment,
    )
    return subscription


# ─── Объявления сверх лимита при смене тарифа ────────────────────────────────

def pause_listings_over_limit(user, plan):
    """
    Тариф закончился: активных объявлений больше лимита нового тарифа — лишние
    уходят в «неактивные» с пометкой plan_paused_status, ничего не удаляется.
    Остаются продвигаемые (VIP, затем топ), потом самые свежие.
    Возвращает число снятых.
    """
    from apps.catalog.limits import LIVE_STATUSES
    from apps.catalog.models import Item

    if plan.listing_limit is None:
        return 0
    live = list(
        Item.objects.select_for_update()
        .filter(owner=user, status__in=LIVE_STATUSES)
        .order_by(*_keep_first_ordering())
        .values_list('pk', 'status')
    )
    extra = live[plan.listing_limit:]
    for status in {s for _, s in extra}:
        Item.objects.filter(pk__in=[pk for pk, s in extra if s == status]).update(
            status=Item.STATUS_INACTIVE, plan_paused_status=status,
        )
    return len(extra)


def restore_paused_listings(user):
    """
    Тариф снова оплачен: объявления, снятые по тарифу, возвращаются в прежний
    статус (без повторной модерации) — сколько позволяет лимит, свежие первыми.
    Снятые владельцем сам не возвращаем. Возвращает число восстановленных.
    """
    from apps.catalog.limits import live_listing_count
    from apps.catalog.models import Item

    from .plans import current_plan

    plan = current_plan(user)
    paused = Item.objects.select_for_update().filter(owner=user, status=Item.STATUS_INACTIVE).exclude(plan_paused_status='')
    if plan.listing_limit is not None:
        room = max(plan.listing_limit - live_listing_count(user), 0)
        paused = paused.order_by('-created_at')[:room]
    restored = 0
    for item in paused:
        item.status = item.plan_paused_status
        item.plan_paused_status = ''
        item.save(update_fields=['status', 'plan_paused_status', 'updated_at'])
        restored += 1
    return restored


def _keep_first_ordering():
    """Порядок «что оставить» при снятии лишних: продвижение, затем свежесть."""
    from apps.catalog.ranking import promotion_ordering

    return [*promotion_ordering(), '-created_at', '-pk']


# ─── Заказы ──────────────────────────────────────────────────────────────────

class OrderNotPayable(Exception):
    """Заказ уже нельзя оплатить: отменён, или тариф больше не подходит."""


def check_order_payable(order):
    """Перед списанием денег (Payme Check/Create, Click Prepare)."""
    if order.status != order.STATUS_PENDING:
        raise OrderNotPayable(order.status)
    if order.kind == order.KIND_PLAN:
        try:
            check_can_buy(order.user, order.plan)
        except BillingError as exc:
            raise OrderNotPayable(exc.detail['code']) from exc
    elif order.item is None or order.item.owner_id != order.user_id or order.item.status != 'approved':
        # Объявление сняли, отклонили или заблокировали, пока заказ ждал оплаты.
        raise OrderNotPayable('item')


@transaction.atomic
def mark_order_paid(order_id, provider=None):
    """
    Деньги получены: применить заказ. Повторный вызов ничего не делает — заказ
    под блокировкой, применяется ровно один раз.
    """
    from .models import BillingOrder

    order = BillingOrder.objects.select_for_update(of=('self',)).select_related('plan', 'user', 'item').get(pk=order_id)
    if order.status == order.STATUS_PAID:
        return order
    order.status = order.STATUS_PAID
    order.paid_at = timezone.now()
    if provider:
        order.provider = provider
    order.save(update_fields=['status', 'paid_at', 'provider'])

    if order.kind == order.KIND_PLAN:
        _apply_plan_order(order)
    else:
        from .promotions import apply_promotion_order
        apply_promotion_order(order)
    return order


def _apply_plan_order(order):
    import logging

    try:
        extend_subscription(order.user, order.plan, amount=order.amount)
    except BillingError as exc:
        # Тариф ниже действующего оплатили в обход проверки (две вкладки):
        # деньги пришли, применить нельзя — сотрудник решает вручную.
        order.needs_attention = f"Не применён: {exc.detail['code']}"
        order.save(update_fields=['needs_attention'])
        logging.getLogger('apps.billing').error('Paid order #%s not applied: %s', order.pk, exc.detail)
        return
    restore_paused_listings(order.user)
    _notify(order.user, 'Тариф оплачен', f'{order.title} — оплачено, спасибо!')


@transaction.atomic
def cancel_order(order_id):
    from .models import BillingOrder

    order = BillingOrder.objects.select_for_update().get(pk=order_id)
    if order.status == order.STATUS_PENDING:
        order.status = order.STATUS_CANCELLED
        order.save(update_fields=['status'])
    return order


def _notify(user, title, message):
    from apps.notifications.models import Notification
    from apps.notifications.tasks import create_notification

    link = settings.OWNER_FRONTEND_BASE_URL.rstrip('/') + '/billing'
    transaction.on_commit(lambda: create_notification(
        user, Notification.TYPE_BILLING, {'title': title, 'message': message, 'link': link},
    ))

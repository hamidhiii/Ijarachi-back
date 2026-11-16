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
from rest_framework.exceptions import ValidationError

from .models import Plan, Subscription, SubscriptionPeriod


def period_days():
    return settings.BILLING_PERIOD_DAYS


def check_can_buy(user, plan):
    """400 с кодом, если этот тариф сейчас купить нельзя."""
    if not plan.is_paid or not plan.is_active:
        raise ValidationError({'code': 'PLAN_NOT_FOR_SALE', 'detail': 'Этот тариф нельзя купить.'})
    current = Subscription.objects.select_related('plan').filter(user=user, ends_at__gt=timezone.now()).first()
    if current and plan.rank < current.plan.rank:
        raise ValidationError({
            'code': 'PLAN_DOWNGRADE_WHILE_ACTIVE',
            'detail': (
                f'Тариф {current.plan.name} действует до {timezone.localtime(current.ends_at):%d.%m.%Y}. '
                'Перейти на тариф ниже можно после его окончания.'
            ),
        })


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
        raise ValidationError({'code': 'PLAN_DOWNGRADE_WHILE_ACTIVE', 'detail': 'Текущий тариф ещё действует.'})
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

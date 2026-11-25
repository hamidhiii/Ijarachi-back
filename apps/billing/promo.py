"""
Акция «START бесплатно до конца января» (решение 25.11.2026; сначала было
«PRO до конца февраля», в тот же день сокращено до START и 31.01.2027).

Каждый, кто регистрируется, пока акция идёт, сразу получает тариф START до конца
дня PROMO_FREE_PRO_UNTIL (по Ташкенту; по умолчанию 31.01.2027). Уже
зарегистрированным без оплаченного тарифа его выдаёт grant_everyone()
(manage.py grant_promo). Потом — как
у любого закончившегося тарифа: напоминания за 3 дня и в последний день,
переход на FREE, объявления сверх лимита FREE уходят в неактивные (не
удаляются) и возвращаются после оплаты.

Подарок пишется в историю периодом с источником «Акция»: в платящих, MRR и
оттоке он не участвует (monitoring.metrics, billing.admin_api).
Пустая PROMO_FREE_PRO_UNTIL — акции нет.
"""
import logging
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Plan, Subscription, SubscriptionPeriod

logger = logging.getLogger('apps.billing')

COMMENT = 'Акция: START бесплатно до конца января'
PROMO_PLAN = Plan.START


def promo_ends_at():
    """Конец акции — полночь после последнего дня (по Ташкенту), или None."""
    value = getattr(settings, 'PROMO_FREE_PRO_UNTIL', '')
    if not value:
        return None
    try:
        last_day = date.fromisoformat(str(value))
    except ValueError:
        logger.error('PROMO_FREE_PRO_UNTIL is not a date: %r', value)
        return None
    return timezone.make_aware(datetime.combine(last_day + timedelta(days=1), time.min))


def is_running(now=None):
    end = promo_ends_at()
    return end is not None and (now or timezone.now()) < end


def promo_user_ids(moment=None):
    """Кто сейчас на тарифе по акции (а не по оплате)."""
    moment = moment or timezone.now()
    return SubscriptionPeriod.objects.filter(
        source=SubscriptionPeriod.SOURCE_PROMO, starts_at__lte=moment, ends_at__gt=moment,
    ).values('user_id')


@transaction.atomic
def grant_signup_promo(user, notify=True):
    """Подарить START пользователю, если акция идёт и оплаченного тарифа нет.

    Подарок по акции, выданный раньше (в т.ч. прежний PRO), приводится к
    текущим условиям. Возвращает подписку или None.
    """
    from .services import _notify

    now = timezone.now()
    end = promo_ends_at()
    if end is None or now >= end or not user.is_active or user.is_staff or user.is_superuser:
        return None
    plan = Plan.objects.filter(code=PROMO_PLAN).first()
    if plan is None:
        return None
    subscription = Subscription.objects.select_for_update().filter(user=user).first()
    promo_period = SubscriptionPeriod.objects.filter(
        user=user, source=SubscriptionPeriod.SOURCE_PROMO, starts_at__lte=now, ends_at__gt=now,
    ).first()
    # Оплачено поверх подарка (продлён дальше акции или другой тариф) — это уже оплата.
    paid = subscription is not None and subscription.ends_at > now and (
        promo_period is None
        or subscription.ends_at > promo_period.ends_at
        or subscription.plan_id != promo_period.plan_id
    )
    if paid:
        return None  # оплаченный тариф — не трогаем
    if promo_period is not None:
        SubscriptionPeriod.objects.filter(pk=promo_period.pk).update(plan=plan, ends_at=end, comment=COMMENT)
        notify = False
    else:
        SubscriptionPeriod.objects.create(
            user=user, plan=plan, starts_at=now, ends_at=end, source=SubscriptionPeriod.SOURCE_PROMO, comment=COMMENT,
        )
    if subscription is None:
        subscription = Subscription.objects.create(user=user, plan=plan, ends_at=end)
    else:
        subscription.plan, subscription.ends_at = plan, end
        subscription.save(update_fields=['plan', 'ends_at', 'updated_at'])
    if notify:
        last_day = timezone.localtime(end - timedelta(seconds=1))
        _notify(user, 'START в подарок', f'Тариф START бесплатно до {last_day:%d.%m.%Y}: '
                                         'до 100 объявлений и CRM-кабинет для учёта броней.')
    logger.info('Promo: START for user %s until %s', user.pk, end)
    return subscription


def grant_everyone():
    """Выдать акцию всем активным пользователям без оплаченного тарифа. Возвращает число."""
    from django.contrib.auth import get_user_model

    if not is_running():
        return 0
    count = 0
    for user in get_user_model().objects.filter(is_active=True, is_staff=False, is_superuser=False).iterator():
        if grant_signup_promo(user) is not None:
            count += 1
    return count

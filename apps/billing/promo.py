"""
Акция «PRO бесплатно до конца февраля» (решение 25.11.2026).

Каждый, кто регистрируется, пока акция идёт, сразу получает тариф PRO до конца
дня PROMO_FREE_PRO_UNTIL (по Ташкенту; по умолчанию 28.02.2027). Потом — как
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

COMMENT = 'Акция: PRO бесплатно до конца февраля'


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
    """Кто сейчас на PRO по акции (а не по оплате)."""
    moment = moment or timezone.now()
    return SubscriptionPeriod.objects.filter(
        source=SubscriptionPeriod.SOURCE_PROMO, starts_at__lte=moment, ends_at__gt=moment,
    ).values('user_id')


@transaction.atomic
def grant_signup_promo(user):
    """Подарить PRO новому пользователю, если акция идёт. Возвращает подписку или None."""
    from .services import _notify

    now = timezone.now()
    end = promo_ends_at()
    if end is None or now >= end or not user.is_active or user.is_staff or user.is_superuser:
        return None
    pro = Plan.objects.filter(code=Plan.PRO).first()
    if pro is None:
        return None
    subscription = Subscription.objects.select_for_update().filter(user=user).first()
    if subscription is not None and subscription.ends_at > now:
        return None  # тариф уже есть — не трогаем
    if subscription is None:
        subscription = Subscription.objects.create(user=user, plan=pro, ends_at=end)
    else:
        subscription.plan, subscription.ends_at = pro, end
        subscription.save(update_fields=['plan', 'ends_at', 'updated_at'])
    SubscriptionPeriod.objects.create(
        user=user, plan=pro, starts_at=now, ends_at=end, source=SubscriptionPeriod.SOURCE_PROMO, comment=COMMENT,
    )
    last_day = timezone.localtime(end - timedelta(seconds=1))
    _notify(user, 'PRO в подарок', f'Спасибо за регистрацию! Тариф PRO бесплатно до {last_day:%d.%m.%Y}: '
                                   'без лимита объявлений, CRM-кабинет, приоритет в поиске.')
    logger.info('Signup promo: PRO for user %s until %s', user.pk, end)
    return subscription

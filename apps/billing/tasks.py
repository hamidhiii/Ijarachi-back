"""
Окончание тарифа и напоминания. Обе задачи идемпотентны: что уже сделано для
данного ends_at, отмечено в подписке, и повторный запуск ничего не повторяет.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger('apps.billing')


@shared_task
def expire_subscriptions():
    """
    Тариф закончился → пользователь на FREE: активные объявления сверх лимита
    уходят в «неактивные» (не удаляются), пользователь получает уведомление.
    """
    from .models import Subscription
    from .plans import free_plan
    from .services import _notify, pause_listings_over_limit

    now = timezone.now()
    due = Subscription.objects.filter(ends_at__lte=now).exclude(expiry_processed_for=F('ends_at'))
    processed = 0
    for subscription_id in due.values_list('pk', flat=True):
        with transaction.atomic():
            subscription = Subscription.objects.select_for_update().select_related('plan', 'user').get(pk=subscription_id)
            if subscription.ends_at > timezone.now() or subscription.expiry_processed_for == subscription.ends_at:
                continue  # продлили или уже обработали параллельно
            free = free_plan()
            paused = pause_listings_over_limit(subscription.user, free)
            subscription.expiry_processed_for = subscription.ends_at
            subscription.save(update_fields=['expiry_processed_for', 'updated_at'])
            message = f'Тариф {subscription.plan.name} закончился, аккаунт переведён на {free.name}.'
            if paused:
                message += (
                    f' {paused} объявл. сверх лимита {free.listing_limit} сняты с публикации, но не удалены —'
                    ' вернутся сами после оплаты тарифа.'
                )
            _notify(subscription.user, 'Тариф закончился', message)
            processed += 1
            logger.info('Subscription #%s expired, %s listings paused', subscription.pk, paused)
    return processed


@shared_task
def remind_subscriptions():
    """Напоминания: за 3 дня до окончания и в последний день (по местной дате)."""
    from .models import Subscription
    from .services import _notify

    today = timezone.localdate()
    sent = 0
    for subscription in Subscription.objects.filter(ends_at__gt=timezone.now()).select_related('plan', 'user'):
        end_day = timezone.localdate(subscription.ends_at)
        ends = timezone.localtime(subscription.ends_at)
        if end_day == today + timedelta(days=3) and subscription.reminder_3d_sent_for != subscription.ends_at:
            field, title = 'reminder_3d_sent_for', 'Тариф заканчивается через 3 дня'
        elif end_day == today and subscription.reminder_last_day_sent_for != subscription.ends_at:
            field, title = 'reminder_last_day_sent_for', 'Тариф заканчивается сегодня'
        else:
            continue
        with transaction.atomic():
            updated = Subscription.objects.filter(pk=subscription.pk, ends_at=subscription.ends_at).exclude(
                **{field: subscription.ends_at},
            ).update(**{field: subscription.ends_at})
            if not updated:
                continue
            _notify(
                subscription.user, title,
                f'Тариф {subscription.plan.name} действует до {ends:%d.%m.%Y %H:%M}. '
                'Продлите его, чтобы объявления сверх бесплатного лимита не снялись с публикации.',
            )
        sent += 1
    return sent


import json
import logging

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer

logger = logging.getLogger('apps.notifications')


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_notification(self, notification_id: int):
    try:
        from .models import Notification
        from .serializers import NotificationSerializer

        notification = Notification.objects.select_related('user').get(pk=notification_id)
        logger.info('Notification queued for user=%s type=%s', notification.user_id, notification.type)

        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.warning('No channel layer configured — skipping live push')
            return

        async_to_sync(channel_layer.group_send)(
            f'notifications_{notification.user_id}',
            {'type': 'notify.push', 'notification': NotificationSerializer(notification).data},
        )
    except Exception as exc:
        logger.error('send_notification failed: %s', exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_telegram_notification(self, notification_id: int):
    """
    Дублирует уведомление в Telegram-бот (тот же, что доставляет OTP), если
    у пользователя есть привязка и он не выключил notify_telegram. Общий путь
    для всех типов уведомлений — раньше каждый вызывающий код сам решал,
    слать ли в Telegram, и это делал только один из них (новая заявка на аренду).
    """
    try:
        from .models import Notification
        from .serializers import NotificationSerializer
        from apps.users.telegram_bot import get_telegram_link, send_telegram_message

        notification = Notification.objects.select_related('user', 'user__profile').get(pk=notification_id)
        try:
            if not notification.user.profile.notify_telegram:
                return
        except Exception:
            pass

        link = get_telegram_link(notification.user.phone)
        if not link:
            return

        data = NotificationSerializer(notification).data
        text = f"🔔 {data['title']}"
        if data.get('description'):
            text += f"\n{data['description']}"
        send_telegram_message(link.chat_id, text)
    except Exception as exc:
        logger.error('send_telegram_notification failed: %s', exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_web_push(self, notification_id: int):
    """
    Push-уведомление в браузер, доходит даже если вкладка/браузер закрыты —
    доставляет сервер через провайдера (FCM и т.п.), не сама вкладка.
    Требует VAPID_PRIVATE_KEY (см. manage.py generate_vapid_keys); без него
    молча ничего не делает — фича считается не настроенной, а не сломанной.
    """
    from django.conf import settings

    if not settings.VAPID_PRIVATE_KEY:
        return
    try:
        from pywebpush import WebPushException, webpush

        from .models import Notification, PushSubscription
        from .serializers import NotificationSerializer

        notification = Notification.objects.select_related('user').get(pk=notification_id)
        data = NotificationSerializer(notification).data
        body = {
            'title': data['title'],
            'body': data.get('description') or '',
            'link': data.get('link'),
            'notification_id': notification.pk,
        }

        for sub in PushSubscription.objects.filter(user=notification.user):
            try:
                webpush(
                    subscription_info=sub.as_webpush_subscription_info(),
                    data=json.dumps(body),
                    vapid_private_key=settings.VAPID_PRIVATE_KEY,
                    vapid_claims={'sub': settings.VAPID_CLAIM_EMAIL},
                )
            except WebPushException as push_exc:
                status_code = getattr(push_exc.response, 'status_code', None)
                if status_code in (404, 410):
                    # Браузер сам протух подписку — без уборки таблица растёт мусором.
                    sub.delete()
                else:
                    logger.warning('web push failed for subscription #%s: %s', sub.pk, push_exc)
    except Exception as exc:
        logger.error('send_web_push failed: %s', exc)
        raise self.retry(exc=exc)


def create_notification(user, type: str, payload: dict):
    from .models import Notification

    notification = Notification.objects.create(user=user, type=type, payload=payload)
    send_notification.delay(notification.pk)
    send_telegram_notification.delay(notification.pk)
    send_web_push.delay(notification.pk)
    return notification

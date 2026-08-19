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


def create_notification(user, type: str, payload: dict):
    from .models import Notification

    notification = Notification.objects.create(user=user, type=type, payload=payload)
    send_notification.delay(notification.pk)
    return notification

import logging

from celery import shared_task

logger = logging.getLogger('apps.notifications')


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_notification(self, notification_id: int):
    try:
        from .models import Notification

        notification = Notification.objects.select_related('user').get(pk=notification_id)
        logger.info('Notification queued for user=%s type=%s', notification.user_id, notification.type)
        # FCM integration can be wired here when production credentials are available.
    except Exception as exc:
        logger.error('send_notification failed: %s', exc)
        raise self.retry(exc=exc)


def create_notification(user, type: str, payload: dict):
    from .models import Notification

    notification = Notification.objects.create(user=user, type=type, payload=payload)
    send_notification.delay(notification.pk)
    return notification

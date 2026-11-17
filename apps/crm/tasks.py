"""
Напоминания о выдаче и возврате (Beat, утром): владельцу и менеджерам — через
уведомления (WebSocket, Telegram, Web Push), как и остальные уведомления.
Отмечается, за какой день напомнили, — повторный запуск не дублирует.
"""
import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('apps.crm')


def _recipients(owner):
    from .models import StaffMember

    managers = StaffMember.objects.filter(owner=owner, role=StaffMember.ROLE_MANAGER).select_related('user')
    return [owner, *(member.user for member in managers)]


@shared_task
def remind_reservations():
    from apps.notifications.models import Notification
    from apps.billing.plans import has_feature
    from apps.notifications.tasks import create_notification

    from .models import Reservation

    today = timezone.localdate()
    sent = 0
    jobs = (
        ('pickup_reminded_on', Reservation.objects.filter(start_date=today, status=Reservation.STATUS_BOOKED), 'Сегодня выдача'),
        ('return_reminded_on', Reservation.objects.filter(end_date=today, status__in=Reservation.OCCUPYING_STATUSES), 'Сегодня возврат'),
    )
    for field, qs, title in jobs:
        for reservation in qs.exclude(**{field: today}).select_related('item', 'client', 'owner'):
            # Тариф кончился (FREE без CRM) — не напоминаем, бронь остаётся.
            if not has_feature(reservation.owner, 'crm'):
                continue
            # Отметка — условным UPDATE: два воркера не пошлют одно и то же дважды.
            if not Reservation.objects.filter(pk=reservation.pk).exclude(**{field: today}).update(**{field: today}):
                continue
            client = f' — {reservation.client.name} {reservation.client.phone}'.rstrip() if reservation.client else ''
            message = f'«{reservation.item.title}» × {reservation.quantity}{client}'
            link = f'{settings.OWNER_FRONTEND_BASE_URL.rstrip("/")}/reservations/{reservation.pk}'
            for user in _recipients(reservation.owner):
                create_notification(user, Notification.TYPE_CRM, {
                    'title': title, 'message': message, 'link': link, 'reservation_id': reservation.pk,
                })
            sent += 1
    logger.info('CRM reminders sent: %s', sent)
    return sent

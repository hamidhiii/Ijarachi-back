import logging
from celery import shared_task
from django.conf import settings

from core.feature_flags import skip_unless_deal_flow

logger = logging.getLogger('apps.bookings')


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
@skip_unless_deal_flow
def notify_owner_new_booking(self, booking_id: int):
    """
    Уведомляет владельца о новом запросе аренды: запись в Notification
    (попадает в список /notifications/ и в счётчик непрочитанных), а
    create_notification сам же дублирует её в Telegram-бот, если владелец
    привязан и не выключил notify_telegram.
    """
    try:
        from apps.bookings.models import Booking
        from apps.notifications.models import Notification
        from apps.notifications.tasks import create_notification

        booking = Booking.objects.select_related('item__owner', 'renter__profile').get(pk=booking_id)
        owner = booking.item.owner

        # Телефон арендатора владельцу до подтверждения не показываем — контакты
        # раскрываются только после подтверждения сделки (contact_revealed_at).
        try:
            renter_name = booking.renter.profile.full_name or 'Арендатор'
        except Exception:
            renter_name = 'Арендатор'

        create_notification(owner, Notification.TYPE_DEAL, {
            'title': 'Новый запрос аренды',
            'message': (
                f'{renter_name} хочет арендовать «{booking.item.title}» '
                f'с {booking.start_date} по {booking.end_date}.'
            ),
            'booking_id': booking.pk,
        })
        logger.info('Deal notification created for owner=%s booking=#%s', owner.phone, booking_id)
    except Exception as exc:
        logger.error('notify_owner_new_booking failed: %s', exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
@skip_unless_deal_flow
def notify_expiring_bookings(self):
    """Daily task: notify renters whose rental expires tomorrow."""
    try:
        from datetime import date, timedelta
        from apps.bookings.models import Booking
        from apps.users.sms import send_sms

        tomorrow = date.today() + timedelta(days=1)
        bookings = Booking.objects.filter(
            end_date=tomorrow,
            status=Booking.STATUS_IN_PROGRESS,
        ).select_related('renter', 'item')

        for booking in bookings:
            message = (
                f'Rentoo: срок аренды "{booking.item.title}" истекает завтра '
                f'({booking.end_date}). Пожалуйста, подготовьте вещь к возврату.'
            )
            logger.info('Expiry reminder → %s for booking #%s', booking.renter.phone, booking.pk)
            send_sms(booking.renter.phone, message)
    except Exception as exc:
        logger.error('notify_expiring_bookings failed: %s', exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
@skip_unless_deal_flow
def release_escrow(self, booking_id: int):
    """
    Сделка завершена: аренда (за вычетом комиссии) — в кошелёк владельцу,
    залог — в кошелёк арендатору. Вся логика и защита от двойного расчёта —
    в apps.bookings.settlement.
    """
    try:
        from apps.bookings.settlement import settle_completed_booking

        settle_completed_booking(booking_id)
    except Exception as exc:
        logger.error('release_escrow failed for booking #%s: %s', booking_id, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
@skip_unless_deal_flow
def expire_stale_bookings(self):
    """
    Отменяет заявки, которые никто не подтвердил и не оплатил дольше
    BOOKING_ABANDON_TIMEOUT_HOURS: без этого неотвеченная заявка держит чужую
    вещь занятой бесконечно.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.bookings.models import Booking
    from apps.bookings.settlement import refund_deposit_on_cancel

    limit = timezone.now() - timedelta(hours=settings.BOOKING_ABANDON_TIMEOUT_HOURS)
    stale = Booking.objects.filter(
        status__in=[Booking.STATUS_DRAFT, Booking.STATUS_PENDING_PAYMENT],
        updated_at__lt=limit,
    ).select_related('item')

    expired = 0
    for booking in stale:
        # Даты освобождаются сами: их занимает бронь, пока она активна. Прежнее
        # «вычеркнуть диапазон из календаря» стирало и даты чужих броней.
        booking.transition_to(Booking.STATUS_CANCELLED)
        refund_deposit_on_cancel(booking, 'Заявка истекла без оплаты')
        expired += 1

    if expired:
        logger.info(
            'Expired %s bookings untouched for more than %sh',
            expired, settings.BOOKING_ABANDON_TIMEOUT_HOURS,
        )
    return expired


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
@skip_unless_deal_flow
def notify_status_change(self, booking_id: int, actor_user_id: int = None):
    """
    Уведомляет о смене статуса сделки: если актёр — одна из сторон, уведомляем
    только вторую; если статус сменил сотрудник/система (actor не арендатор
    и не владелец, включая None), уведомляем обе стороны.
    """
    try:
        from apps.bookings.models import Booking
        from apps.notifications.models import Notification
        from apps.notifications.tasks import create_notification

        booking = Booking.objects.select_related('item__owner', 'renter').get(pk=booking_id)
        parties = [booking.renter, booking.item.owner]
        recipients = [u for u in parties if u.id != actor_user_id]
        if not recipients:
            recipients = parties

        for user in recipients:
            role = 'renter' if user.id == booking.renter_id else 'owner'
            create_notification(user, Notification.TYPE_DEAL, {
                'title': 'Статус сделки изменился',
                'message': f'«{booking.item.title}»: {booking.progress_for(role)}.',
                'booking_id': booking.pk,
            })
    except Exception as exc:
        logger.error('notify_status_change failed for booking #%s: %s', booking_id, exc)
        raise self.retry(exc=exc)

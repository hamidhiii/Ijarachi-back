import logging
from celery import shared_task
from django.conf import settings

logger = logging.getLogger('apps.bookings')


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
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

        try:
            renter_name = booking.renter.profile.full_name or booking.renter.phone
        except Exception:
            renter_name = booking.renter.phone

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
def release_escrow(self, booking_id: int):
    """
    Triggered when booking is COMPLETED.
    Platform keeps the configured commission, owner gets the payout credited to wallet_balance.
    """
    from decimal import Decimal
    try:
        from apps.bookings.models import Booking
        from apps.payments.models import Payment, Transaction
        from django.db import transaction as db_transaction

        booking = Booking.objects.select_related('item__owner__profile').get(pk=booking_id)

        cash_payment = Payment.objects.filter(booking=booking, provider=Payment.PROVIDER_CASH).first()
        if cash_payment:
            # Наличные владелец получил из рук в руки: платформа их не держала и
            # не выплачивает. Комиссия по таким сделкам автоматически не удерживается.
            cash_payment.status = Payment.STATUS_COMPLETED
            cash_payment.save(update_fields=['status', 'updated_at'])
            booking.status = Booking.STATUS_COMPLETED
            booking.escrow_status = Booking.ESCROW_NONE
            booking.save(update_fields=['status', 'escrow_status', 'updated_at'])
            logger.info('Booking #%s settled in cash, no payout from escrow', booking_id)
            return

        payment = Payment.objects.filter(
            booking=booking,
            status=Payment.STATUS_PAID,
        ).first()

        if not payment:
            logger.warning('No paid payment found for booking #%s during escrow release', booking_id)
            return

        # amount stored in tiyin (×100), convert to sums
        total_sums = Decimal(str(payment.amount)) / 100
        commission_rate = Decimal(str(settings.PLATFORM_COMMISSION_PERCENT)) / Decimal('100')
        rental_income = booking.price_per_day * booking.days
        owner_payout = (rental_income * (Decimal('1') - commission_rate)).quantize(Decimal('1'))

        with db_transaction.atomic():
            profile = booking.item.owner.profile
            profile.wallet_balance += owner_payout
            profile.save(update_fields=['wallet_balance'])

            payment.status = Payment.STATUS_COMPLETED
            payment.save(update_fields=['status', 'updated_at'])

            booking.status = Booking.STATUS_COMPLETED
            booking.escrow_status = Booking.ESCROW_RELEASED
            booking.save(update_fields=['status', 'escrow_status', 'updated_at'])

            Transaction.objects.create(
                booking=booking,
                payment=payment,
                user=booking.item.owner,
                type=Transaction.TYPE_PAYOUT,
                amount=owner_payout,
                currency='UZS',
                metadata={'source': 'release_escrow'},
            )

        logger.info(
            'Escrow released for booking #%s: total=%s sums, owner payout=%s sums',
            booking_id, total_sums, owner_payout,
        )

    except Exception as exc:
        logger.error('release_escrow failed for booking #%s: %s', booking_id, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def expire_stale_bookings(self):
    """
    Отменяет заявки, которые никто не подтвердил и не оплатил дольше
    BOOKING_ABANDON_TIMEOUT_HOURS, и освобождает даты в календаре: без этого
    неотвеченная заявка держит чужую вещь занятой бесконечно.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.bookings.models import Booking
    from apps.catalog.models import ItemAvailability

    limit = timezone.now() - timedelta(hours=settings.BOOKING_ABANDON_TIMEOUT_HOURS)
    stale = Booking.objects.filter(
        status__in=[Booking.STATUS_DRAFT, Booking.STATUS_PENDING_PAYMENT],
        updated_at__lt=limit,
    ).select_related('item')

    expired = 0
    for booking in stale:
        try:
            avail = ItemAvailability.objects.get(item=booking.item)
            avail.unblock_range(booking.start_date, booking.end_date)
        except ItemAvailability.DoesNotExist:
            pass
        booking.transition_to(Booking.STATUS_CANCELLED)
        expired += 1

    if expired:
        logger.info(
            'Expired %s bookings untouched for more than %sh',
            expired, settings.BOOKING_ABANDON_TIMEOUT_HOURS,
        )
    return expired


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
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

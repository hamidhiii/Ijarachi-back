import logging
from celery import shared_task
from django.conf import settings

logger = logging.getLogger('apps.bookings')


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def notify_owner_new_booking(self, booking_id: int):
    """Notify item owner about a new booking request."""
    try:
        from apps.bookings.models import Booking
        from apps.users.sms import send_otp_sms

        booking = Booking.objects.select_related('item__owner', 'renter').get(pk=booking_id)
        owner = booking.item.owner
        message = (
            f'SYNTH Share: новый запрос на аренду "{booking.item.title}" '
            f'от {booking.renter.phone}. '
            f'Даты: {booking.start_date} — {booking.end_date}.'
        )
        logger.info('Notifying owner %s for booking #%s', owner.phone, booking_id)
        # Reuse SMS utility (non-OTP message)
        from apps.users.sms import _get_eskiz_token
        import requests
        token = _get_eskiz_token()
        if token:
            requests.post(
                'https://notify.eskiz.uz/api/message/sms/send',
                headers={'Authorization': f'Bearer {token}'},
                data={'mobile_phone': owner.phone.lstrip('+'), 'message': message, 'from': '4546'},
                timeout=10,
            )
    except Exception as exc:
        logger.error('notify_owner_new_booking failed: %s', exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def notify_expiring_bookings(self):
    """Daily task: notify renters whose rental expires tomorrow."""
    try:
        from datetime import date, timedelta
        from apps.bookings.models import Booking
        import requests

        tomorrow = date.today() + timedelta(days=1)
        bookings = Booking.objects.filter(
            end_date=tomorrow,
            status=Booking.STATUS_ACTIVE,
        ).select_related('renter', 'item')

        from apps.users.sms import _get_eskiz_token
        token = _get_eskiz_token()

        for booking in bookings:
            message = (
                f'SYNTH Share: срок аренды "{booking.item.title}" истекает завтра '
                f'({booking.end_date}). Пожалуйста, подготовьте вещь к возврату.'
            )
            logger.info('Expiry reminder → %s for booking #%s', booking.renter.phone, booking.pk)
            if token:
                requests.post(
                    'https://notify.eskiz.uz/api/message/sms/send',
                    headers={'Authorization': f'Bearer {token}'},
                    data={
                        'mobile_phone': booking.renter.phone.lstrip('+'),
                        'message': message,
                        'from': '4546',
                    },
                    timeout=10,
                )
    except Exception as exc:
        logger.error('notify_expiring_bookings failed: %s', exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def release_escrow(self, booking_id: int):
    """
    Triggered when booking is COMPLETED.
    Platform keeps 15%, owner gets 85% credited to wallet_balance.
    """
    from decimal import Decimal
    try:
        from apps.bookings.models import Booking
        from apps.payments.models import Payment
        from django.db import transaction as db_transaction

        booking = Booking.objects.select_related('item__owner__profile').get(pk=booking_id)
        payment = Payment.objects.filter(
            booking=booking,
            status=Payment.STATUS_PAID,
        ).first()

        if not payment:
            logger.warning('No paid payment found for booking #%s during escrow release', booking_id)
            return

        # amount stored in tiyin (×100), convert to sums
        total_sums = Decimal(str(payment.amount)) / 100
        owner_payout = (total_sums * Decimal('0.85')).quantize(Decimal('1'))

        with db_transaction.atomic():
            profile = booking.item.owner.profile
            profile.wallet_balance += owner_payout
            profile.save(update_fields=['wallet_balance'])

            payment.status = Payment.STATUS_COMPLETED
            payment.save(update_fields=['status', 'updated_at'])

        logger.info(
            'Escrow released for booking #%s: total=%s sums, owner payout=%s sums (85%%)',
            booking_id, total_sums, owner_payout,
        )

    except Exception as exc:
        logger.error('release_escrow failed for booking #%s: %s', booking_id, exc)
        raise self.retry(exc=exc)

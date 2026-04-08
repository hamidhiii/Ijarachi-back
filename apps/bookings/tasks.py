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
    Marks payment as ready for payout (escrow release logic placeholder).
    """
    try:
        from apps.bookings.models import Booking
        from apps.payments.models import Payment

        booking = Booking.objects.get(pk=booking_id)
        payment = Payment.objects.filter(
            booking=booking,
            status=Payment.STATUS_PAID,
        ).first()

        if payment:
            logger.info(
                'Escrow release triggered for booking #%s, payment #%s, amount=%s',
                booking_id, payment.pk, payment.amount
            )
            # TODO: integrate with actual payout API (Payme/Click withdrawal)
            # For now, just log. The transit account holds the funds.
        else:
            logger.warning('No paid payment found for booking #%s during escrow release', booking_id)

    except Exception as exc:
        logger.error('release_escrow failed for booking #%s: %s', booking_id, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True)
def auto_complete_inspections(self):
    """
    Cron task running hourly.
    Automatically closes bookings in INSPECTION status if 24 hours have passed without action.
    """
    try:
        from datetime import timedelta
        from django.utils import timezone
        from apps.bookings.models import Booking

        threshold = timezone.now() - timedelta(hours=24)
        expired_bookings = Booking.objects.filter(
            status=Booking.STATUS_INSPECTION,
            updated_at__lt=threshold,
        )

        for booking in expired_bookings:
            logger.warning('Auto-completing inspection for booking #%s after 24h timeout.', booking.pk)
            booking.transition_to(Booking.STATUS_COMPLETED)
            release_escrow.delay(booking.pk)
    
    except Exception as exc:
        logger.error('auto_complete_inspections failed: %s', exc)
        raise self.retry(exc=exc)

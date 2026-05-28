import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def charge_myid_first_deal_cost(self, user_id: int, booking_id: int):
    try:
        from apps.payments.models import Transaction
        from apps.users.models import CustomUser
        from apps.bookings.models import Booking

        user = CustomUser.objects.get(pk=user_id)
        booking = Booking.objects.get(pk=booking_id)
        already_charged = Transaction.objects.filter(
            user=user,
            type=Transaction.TYPE_MYID_EXPENSE,
        ).exists()
        if already_charged:
            return

        Transaction.objects.create(
            booking=booking,
            user=user,
            type=Transaction.TYPE_MYID_EXPENSE,
            amount=settings.MYID_FIRST_DEAL_COST,
            currency='UZS',
            metadata={'reason': 'first_deal_myid_cost'},
        )
        logger.info('MyID first deal cost recorded for user=%s booking=%s', user_id, booking_id)
    except Exception as exc:
        logger.error('charge_myid_first_deal_cost failed: %s', exc)
        raise self.retry(exc=exc)

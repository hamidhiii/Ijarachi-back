import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger('apps.delivery')


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def create_yandex_delivery_order(self, booking_id: int):
    try:
        from apps.bookings.models import Booking
        from .models import DeliveryOrder

        booking = Booking.objects.select_related('item__owner', 'renter').get(pk=booking_id)
        order, _ = DeliveryOrder.objects.get_or_create(
            booking=booking,
            direction=DeliveryOrder.DIRECTION_FORWARD,
            defaults={
                'cost': booking.delivery_cost,
                'status': 'created',
                'yandex_order_id': f'rentoo-{booking.pk}-forward',
                'raw_payload': {'provider': 'yandex', 'mode': 'deferred'},
            },
        )
        booking.yandex_delivery_order_id = order.yandex_order_id
        booking.yandex_delivery_status = order.status
        booking.save(update_fields=['yandex_delivery_order_id', 'yandex_delivery_status', 'updated_at'])
        logger.info('Yandex delivery order created for booking #%s', booking.pk)
    except Exception as exc:
        logger.error('create_yandex_delivery_order failed: %s', exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def create_return_delivery_orders(self):
    try:
        from apps.bookings.models import Booking
        from .models import DeliveryOrder

        target_date = timezone.localdate() + timedelta(days=1)
        qs = Booking.objects.filter(
            end_date=target_date,
            delivery_method=Booking.DELIVERY_DELIVERY,
            status=Booking.STATUS_IN_PROGRESS,
        )
        for booking in qs:
            DeliveryOrder.objects.get_or_create(
                booking=booking,
                direction=DeliveryOrder.DIRECTION_RETURN,
                defaults={
                    'cost': booking.delivery_cost,
                    'status': 'created',
                    'yandex_order_id': f'rentoo-{booking.pk}-return',
                    'raw_payload': {'provider': 'yandex', 'mode': 'return'},
                },
            )
        logger.info('Return delivery scheduler processed %s bookings', qs.count())
    except Exception as exc:
        logger.error('create_return_delivery_orders failed: %s', exc)
        raise self.retry(exc=exc)

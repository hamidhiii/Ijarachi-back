from django.db import models


class DeliveryOrder(models.Model):
    DIRECTION_FORWARD = 'forward'
    DIRECTION_RETURN = 'return'

    DIRECTION_CHOICES = [
        (DIRECTION_FORWARD, 'Forward'),
        (DIRECTION_RETURN, 'Return'),
    ]

    booking = models.ForeignKey('bookings.Booking', on_delete=models.CASCADE, related_name='delivery_orders')
    direction = models.CharField(max_length=20, choices=DIRECTION_CHOICES, default=DIRECTION_FORWARD)
    yandex_order_id = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=80, default='created')
    cost = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    raw_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.booking_id}:{self.direction}:{self.status}'

from django.db.models.signals import post_init, post_save
from django.dispatch import receiver

from .models import Booking, BookingStatusLog

# Снимок статусов, сделанный при загрузке объекта из БД: сравнение с ним на
# post_save показывает, был ли переход, без дополнительного запроса.
SNAPSHOT_ATTR = '_status_snapshot'


@receiver(post_init, sender=Booking)
def remember_status(sender, instance, **kwargs):
    setattr(instance, SNAPSHOT_ATTR, (instance.status, instance.escrow_status))


@receiver(post_save, sender=Booking)
def log_status_change(sender, instance, created, **kwargs):
    current = (instance.status, instance.escrow_status)
    previous = None if created else getattr(instance, SNAPSHOT_ATTR, None)

    if not created and previous == current:
        return

    BookingStatusLog.objects.create(
        booking=instance,
        from_status=previous[0] if previous else '',
        to_status=instance.status,
        from_escrow=previous[1] if previous else '',
        to_escrow=instance.escrow_status,
    )
    setattr(instance, SNAPSHOT_ATTR, current)

from django.db.models.signals import post_init, post_save
from django.dispatch import receiver

from .models import Booking, BookingStatusLog

# Снимок статусов, сделанный при загрузке объекта из БД: сравнение с ним на
# post_save показывает, был ли переход, без дополнительного запроса.
SNAPSHOT_ATTR = '_status_snapshot'


@receiver(post_init, sender=Booking)
def remember_status(sender, instance, **kwargs):
    # Инстансы, собранные из частично загруженного queryset (.only()/.defer(),
    # или служебные объекты, которые Django строит при каскадном удалении/его
    # превью в админке), могут не иметь status/escrow_status среди загруженных
    # полей. Обращение к отложенному полю само запускает refresh_from_db(),
    # который создаёт новый инстанс → снова post_init → снова отложенное поле
    # (уже другое) — бесконечная рекурсия. Пропускаем снапшот в этом случае:
    # смысла в нём всё равно нет, раз оба поля не были явно загружены.
    deferred = instance.get_deferred_fields()
    if 'status' in deferred or 'escrow_status' in deferred:
        return
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

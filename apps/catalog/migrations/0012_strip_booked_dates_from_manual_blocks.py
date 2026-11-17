"""
ItemAvailability.blocked_dates теперь — только ручные блокировки владельца.
Раньше туда же писались даты броней; убираем дни, которые покрыты бронями
(кроме черновиков и отмен — те даты не держали или уже вернули), чтобы они
не остались закрытыми навсегда, когда бронь отменят или она закончится.
Дни активных броней по-прежнему заняты — теперь их считают по самим броням.
"""
from datetime import timedelta

from django.db import migrations

BOOKING_STATUSES_THAT_BLOCKED = [
    'pending_payment', 'paid', 'in_progress', 'returned', 'completed', 'disputed',
]


def strip_booked_dates(apps, schema_editor):
    ItemAvailability = apps.get_model('catalog', 'ItemAvailability')
    Booking = apps.get_model('bookings', 'Booking')

    for availability in ItemAvailability.objects.exclude(blocked_dates=[]):
        booked = set()
        ranges = Booking.objects.filter(
            item_id=availability.item_id, status__in=BOOKING_STATUSES_THAT_BLOCKED,
        ).values_list('start_date', 'end_date')
        for start, end in ranges:
            current = start
            while current <= end:
                booked.add(current.isoformat())
                current += timedelta(days=1)
        manual = [day for day in availability.blocked_dates if day not in booked]
        if manual != availability.blocked_dates:
            availability.blocked_dates = manual
            availability.save(update_fields=['blocked_dates'])


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0011_availability_manual_only'),
        ('bookings', '0012_backfill_deposit_status'),
    ]

    operations = [
        migrations.RunPython(strip_booked_dates, migrations.RunPython.noop),
    ]

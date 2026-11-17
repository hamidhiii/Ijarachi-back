"""
Статус залога для сделок, созданных до его появления.

До этой миграции залог нигде не возвращался: выплата по завершении уходила
владельцу, а залог оставался у платформы. Поэтому у уже рассчитанных
(escrow released) сделок с залогом статус — held: деньги по-прежнему у
платформы, их нужно вернуть арендаторам вручную. Это честнее, чем записать
«возвращён» задним числом.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    Booking = apps.get_model('bookings', 'Booking')

    Booking.objects.filter(deposit_amount__lte=0).update(deposit_status='none')
    with_deposit = Booking.objects.filter(deposit_amount__gt=0)
    with_deposit.filter(escrow_status='none').update(deposit_status='none')
    with_deposit.filter(escrow_status='pending').update(deposit_status='pending')
    with_deposit.filter(escrow_status__in=['held', 'frozen', 'released']).update(deposit_status='held')
    with_deposit.filter(escrow_status='refunded').update(deposit_status='refunded')
    # Отменённые неоплаченные залога не ждут.
    with_deposit.filter(status='cancelled', escrow_status='pending').update(deposit_status='none')


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0011_deposit_status_and_history'),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]

from django.db import migrations, models


def map_old_statuses(apps, schema_editor):
    Booking = apps.get_model('bookings', 'Booking')
    mapping = {
        'created': 'draft',
        'waiting_payment': 'pending_payment',
        'paid_escrow': 'paid',
        'returning': 'returned',
        'dispute': 'disputed',
        'payment_pending': 'pending_payment',
        'placed': 'paid',
        'pickup_scheduled': 'in_progress',
        'picked_up': 'in_progress',
        'active': 'in_progress',
    }
    for old, new in mapping.items():
        Booking.objects.filter(status=old).update(status=new)


def reverse_statuses(apps, schema_editor):
    Booking = apps.get_model('bookings', 'Booking')
    mapping = {
        'pending_payment': 'payment_pending',
        'paid': 'placed',
        'in_progress': 'active',
        'disputed': 'cancelled',
        'returned': 'active',
        'draft': 'payment_pending',
    }
    for old, new in mapping.items():
        Booking.objects.filter(status=old).update(status=new)


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0004_deliverer_booking_delivery_address_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='contact_revealed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='delivery_comment',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='delivery_cost',
            field=models.DecimalField(decimal_places=0, default=0, max_digits=12, verbose_name='Стоимость доставки'),
        ),
        migrations.AddField(
            model_name='booking',
            name='delivery_method',
            field=models.CharField(choices=[('pickup', 'Pickup'), ('delivery', 'Delivery')], default='pickup', max_length=20),
        ),
        migrations.AddField(
            model_name='booking',
            name='dispute_reason',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='escrow_amount',
            field=models.DecimalField(decimal_places=0, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name='booking',
            name='escrow_status',
            field=models.CharField(choices=[('pending', 'Pending'), ('held', 'Held'), ('released', 'Released'), ('refunded', 'Refunded'), ('frozen', 'Frozen')], default='pending', max_length=20),
        ),
        migrations.AddField(
            model_name='booking',
            name='returned_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='yandex_delivery_order_id',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='booking',
            name='yandex_delivery_status',
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.RunPython(map_old_statuses, reverse_statuses),
        migrations.AlterField(
            model_name='booking',
            name='commission_amount',
            field=models.DecimalField(decimal_places=0, max_digits=12, verbose_name='Комиссия платформы'),
        ),
        migrations.AlterField(
            model_name='booking',
            name='status',
            field=models.CharField(choices=[('draft', 'Draft'), ('pending_payment', 'Pending payment'), ('paid', 'Paid'), ('in_progress', 'In progress'), ('returned', 'Returned'), ('completed', 'Completed'), ('cancelled', 'Cancelled'), ('disputed', 'Disputed')], default='draft', max_length=30, verbose_name='Статус'),
        ),
    ]

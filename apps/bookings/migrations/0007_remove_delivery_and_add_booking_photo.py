import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0006_deal_review'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BookingPhoto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('before', 'Before'), ('after', 'After'), ('issue', 'Issue')], max_length=20)),
                ('image', models.ImageField(upload_to='deal_evidence/')),
                ('comment', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('booking', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='photos', to='bookings.booking')),
                ('uploaded_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='booking_photos', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['created_at'],
            },
        ),
        migrations.RemoveField(
            model_name='booking',
            name='deliverer',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='delivery_address',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='delivery_comment',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='delivery_cost',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='delivery_eta',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='delivery_lat',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='delivery_lng',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='delivery_method',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='pickup_eta',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='yandex_delivery_order_id',
        ),
        migrations.RemoveField(
            model_name='booking',
            name='yandex_delivery_status',
        ),
        migrations.DeleteModel(
            name='Deliverer',
        ),
        migrations.RunSQL(
            sql='DROP TABLE IF EXISTS delivery_deliveryorder',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

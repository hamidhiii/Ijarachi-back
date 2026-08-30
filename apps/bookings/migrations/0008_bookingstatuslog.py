from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0007_remove_delivery_and_add_booking_photo'),
    ]

    operations = [
        migrations.CreateModel(
            name='BookingStatusLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('from_status', models.CharField(blank=True, max_length=30, verbose_name='Статус до')),
                ('to_status', models.CharField(max_length=30, verbose_name='Статус после')),
                ('from_escrow', models.CharField(blank=True, max_length=20, verbose_name='Эскроу до')),
                ('to_escrow', models.CharField(blank=True, max_length=20, verbose_name='Эскроу после')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('booking', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='status_logs',
                    to='bookings.booking',
                    verbose_name='Сделка',
                )),
            ],
            options={
                'verbose_name': 'Переход статуса сделки',
                'verbose_name_plural': 'Переходы статусов сделок',
                'ordering': ['created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='bookingstatuslog',
            index=models.Index(fields=['booking', 'created_at'], name='bookings_bsl_booking_idx'),
        ),
    ]

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('bookings', '0005_deal_contract'),
    ]

    operations = [
        migrations.CreateModel(
            name='DeliveryOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('direction', models.CharField(choices=[('forward', 'Forward'), ('return', 'Return')], default='forward', max_length=20)),
                ('yandex_order_id', models.CharField(blank=True, max_length=120)),
                ('status', models.CharField(default='created', max_length=80)),
                ('cost', models.DecimalField(decimal_places=0, default=0, max_digits=12)),
                ('raw_payload', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('booking', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='delivery_orders', to='bookings.booking')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]

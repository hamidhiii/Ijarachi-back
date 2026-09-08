from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0008_bookingstatuslog'),
    ]

    operations = [
        migrations.AlterField(
            model_name='booking',
            name='escrow_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('held', 'Held'),
                    ('released', 'Released'),
                    ('refunded', 'Refunded'),
                    ('frozen', 'Frozen'),
                    ('none', 'Без эскроу (наличные)'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0009_booking_escrow_none'),
    ]

    operations = [
        migrations.AlterField(
            model_name='booking',
            name='status',
            field=models.CharField(
                choices=[
                    ('draft', 'Черновик'),
                    ('pending_payment', 'Ждёт оплату'),
                    ('paid', 'Оплачено'),
                    ('in_progress', 'Аренда идёт'),
                    ('returned', 'Возвращено'),
                    ('completed', 'Завершено'),
                    ('cancelled', 'Отменено'),
                    ('disputed', 'Спор'),
                ],
                default='draft',
                max_length=30,
                verbose_name='Статус',
            ),
        ),
        migrations.AlterField(
            model_name='booking',
            name='escrow_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Ожидает удержания'),
                    ('held', 'Удержано'),
                    ('released', 'Выплачено владельцу'),
                    ('refunded', 'Возвращено арендатору'),
                    ('frozen', 'Заморожено'),
                    ('none', 'Без эскроу (наличные)'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
    ]

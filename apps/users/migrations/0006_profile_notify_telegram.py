from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_telegramlink'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='notify_telegram',
            field=models.BooleanField(default=True, verbose_name='Дублировать уведомления в Telegram'),
        ),
    ]

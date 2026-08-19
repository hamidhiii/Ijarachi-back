from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0004_kyc_own_pipeline'),
    ]

    operations = [
        migrations.CreateModel(
            name='TelegramLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone', models.CharField(max_length=20, unique=True, verbose_name='Телефон')),
                ('chat_id', models.BigIntegerField(verbose_name='Telegram chat_id')),
                ('telegram_user_id', models.BigIntegerField(blank=True, null=True, verbose_name='Telegram user_id')),
                ('username', models.CharField(blank=True, max_length=64, verbose_name='Telegram username')),
                ('linked_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Привязка Telegram',
                'verbose_name_plural': 'Привязки Telegram',
            },
        ),
    ]

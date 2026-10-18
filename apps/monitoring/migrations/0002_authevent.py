from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuthEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event', models.CharField(choices=[
                    ('visit', 'Зашёл на сайт'),
                    ('auth_opened', 'Открыл форму входа'),
                    ('phone_entered', 'Ввёл номер'),
                    ('client_error', 'Ошибка на странице'),
                    ('otp_sent', 'Код отправлен'),
                    ('otp_telegram_required', 'Нужно подтвердить Telegram'),
                    ('otp_cooldown', 'Слишком частый запрос кода'),
                    ('otp_send_failed', 'Код не удалось отправить'),
                    ('otp_invalid_input', 'Неверный номер телефона'),
                    ('verify_failed', 'Неверный или устаревший код'),
                    ('verify_invalid_input', 'Некорректный ввод кода'),
                    ('login_ok', 'Вошёл'),
                    ('register_ok', 'Зарегистрировался'),
                ], max_length=30, verbose_name='Событие')),
                ('phone', models.CharField(blank=True, max_length=20, verbose_name='Телефон')),
                ('visitor_id', models.CharField(blank=True, db_index=True, max_length=64, verbose_name='Посетитель')),
                ('ip', models.GenericIPAddressField(blank=True, null=True, verbose_name='IP')),
                ('user_agent', models.CharField(blank=True, max_length=200)),
                ('detail', models.CharField(blank=True, max_length=300, verbose_name='Подробности')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Событие входа',
                'verbose_name_plural': 'События входа',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['event', 'created_at'], name='authevent_event_created_idx')],
            },
        ),
    ]

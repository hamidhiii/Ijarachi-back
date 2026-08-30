from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MonitorAccess',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_active', models.BooleanField(default=True, verbose_name='Доступ включён')),
                ('can_view_deals', models.BooleanField(default=True, verbose_name='Сделки')),
                ('can_view_disputes', models.BooleanField(default=True, verbose_name='Споры')),
                ('can_view_kyc', models.BooleanField(default=False, verbose_name='KYC')),
                ('can_view_payments', models.BooleanField(default=False, verbose_name='Платежи')),
                ('can_view_errors', models.BooleanField(default=True, verbose_name='Ошибки')),
                ('can_manage_access', models.BooleanField(default=False, verbose_name='Управление доступами')),
                ('note', models.CharField(blank=True, max_length=200, verbose_name='Заметка')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='granted_monitor_access',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Кем выдан',
                )),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='monitor_access',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Пользователь',
                )),
            ],
            options={
                'verbose_name': 'Доступ к монитору',
                'verbose_name_plural': 'Доступы к монитору',
                'ordering': ['-created_at'],
            },
        ),
    ]

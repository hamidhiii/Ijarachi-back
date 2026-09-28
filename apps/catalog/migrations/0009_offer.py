import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('catalog', '0008_item_is_negotiable'),
    ]

    operations = [
        migrations.CreateModel(
            name='Offer',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=0, max_digits=12, verbose_name='Предложенная цена за сутки (сум)')),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Ожидает ответа'),
                        ('accepted', 'Принято'),
                        ('rejected', 'Отклонено'),
                        ('withdrawn', 'Снято предложением'),
                    ],
                    default='pending', max_length=20, verbose_name='Статус',
                )),
                ('proposed_by', models.CharField(
                    choices=[('renter', 'Арендатор'), ('owner', 'Владелец')],
                    default='renter', max_length=10, verbose_name='Кто предложил',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='offers', to='catalog.item', verbose_name='Объявление')),
                ('renter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='price_offers', to=settings.AUTH_USER_MODEL, verbose_name='Арендатор')),
            ],
            options={
                'verbose_name': 'Предложение цены',
                'verbose_name_plural': 'Предложения цены',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='offer',
            index=models.Index(fields=['item', 'renter', '-created_at'], name='catalog_off_item_id_e6c9a1_idx'),
        ),
    ]

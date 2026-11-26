"""С какого сайта шаг входа: rentoo.uz, owner.rentoo.uz или Mini App."""
from django.db import migrations, models


def backfill_visits(apps, schema_editor):
    # У «Зашёл на сайт» источник и раньше лежал в detail — переносим его.
    AuthEvent = apps.get_model('monitoring', 'AuthEvent')
    for source in ('web', 'owner', 'tma'):
        AuthEvent.objects.filter(event='visit', detail=source).update(source=source)
    # Вход через Mini App узнаётся по detail.
    AuthEvent.objects.filter(detail__startswith='telegram_webapp').update(source='tma')


class Migration(migrations.Migration):

    dependencies = [
        ('monitoring', '0004_support_section'),
    ]

    operations = [
        migrations.AddField(
            model_name='authevent',
            name='source',
            field=models.CharField(
                blank=True,
                choices=[('web', 'rentoo.uz'), ('owner', 'owner.rentoo.uz'), ('tma', 'Telegram Mini App')],
                max_length=10,
                verbose_name='Сайт',
            ),
        ),
        migrations.RunPython(backfill_visits, migrations.RunPython.noop),
    ]

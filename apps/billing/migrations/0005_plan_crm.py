"""CRM (кабинет owner.rentoo.uz) — с тарифа START; на FREE только объявления (решение 17.11.2026)."""
from django.db import migrations, models


def enable(apps, schema_editor):
    apps.get_model('billing', 'Plan').objects.exclude(code='free').update(crm=True)


class Migration(migrations.Migration):
    dependencies = [('billing', '0004_promotion')]

    operations = [
        migrations.AddField(
            model_name='plan', name='crm',
            field=models.BooleanField(default=False, verbose_name='CRM (кабинет)'),
        ),
        migrations.RunPython(enable, migrations.RunPython.noop),
    ]

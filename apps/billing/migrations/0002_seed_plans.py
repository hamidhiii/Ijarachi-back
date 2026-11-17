"""Четыре тарифа из решения 16.11.2026. Цены и права дальше правятся в админке."""
from django.db import migrations

PLANS = [
    # code, name, price, listing_limit, search_priority, staff_access, statistics, branches, data_export, rank
    ('free', 'FREE', 0, 10, False, False, False, False, False, 0),
    ('start', 'START', 99000, 100, False, False, False, False, False, 1),
    ('business', 'BUSINESS', 199000, 300, True, True, True, False, False, 2),
    ('pro', 'PRO', 399000, None, True, True, True, True, True, 3),
]


def seed(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    for code, name, price, limit, priority, staff, stats, branches, export, rank in PLANS:
        Plan.objects.update_or_create(code=code, defaults={
            'name': name, 'price': price, 'listing_limit': limit,
            'search_priority': priority, 'staff_access': staff, 'statistics': stats,
            'branches': branches, 'data_export': export, 'rank': rank, 'is_active': True,
        })


class Migration(migrations.Migration):
    dependencies = [('billing', '0001_initial')]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

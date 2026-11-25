"""Новый раздел «Техподдержка»: сотрудникам с готовой ролью — уровень из роли, остальным — none."""
from django.db import migrations


def add_support(apps, schema_editor):
    from apps.monitoring.roles import ROLES

    MonitorAccess = apps.get_model('monitoring', 'MonitorAccess')
    for access in MonitorAccess.objects.all():
        permissions = dict(access.permissions or {})
        if 'support' in permissions:
            continue
        preset = ROLES.get(access.role)
        permissions['support'] = preset[1]['support'] if preset else 'none'
        access.permissions = permissions
        access.save(update_fields=['permissions'])


class Migration(migrations.Migration):
    dependencies = [('monitoring', '0003_panel_roles')]
    operations = [migrations.RunPython(add_support, migrations.RunPython.noop)]

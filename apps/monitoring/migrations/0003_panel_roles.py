from django.db import migrations, models


def flags_to_permissions(apps, schema_editor):
    """Старые галочки монитора → матрица прав панели."""
    from apps.monitoring.roles import role_for

    MonitorAccess = apps.get_model('monitoring', 'MonitorAccess')
    for access in MonitorAccess.objects.all():
        permissions = {
            'analytics': 'view',
            'users': 'view',
            'listings': 'view',
            'billing': 'view' if access.can_view_payments else 'none',
            'payments': 'view' if access.can_view_payments else 'none',
            'deals': 'view' if (access.can_view_deals or access.can_view_disputes) else 'none',
            'kyc': 'view' if access.can_view_kyc else 'none',
            'staff': 'edit' if access.can_manage_access else 'none',
        }
        access.permissions = permissions
        access.role = role_for(permissions)
        access.save(update_fields=['permissions', 'role'])


class Migration(migrations.Migration):
    dependencies = [('monitoring', '0002_authevent')]

    operations = [
        migrations.AddField(model_name='monitoraccess', name='role',
                            field=models.CharField(default='viewer', max_length=20, verbose_name='Роль')),
        migrations.AddField(model_name='monitoraccess', name='permissions',
                            field=models.JSONField(blank=True, default=dict, verbose_name='Права по разделам')),
        migrations.RunPython(flags_to_permissions, migrations.RunPython.noop),
    ]

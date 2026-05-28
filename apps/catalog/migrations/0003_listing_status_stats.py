from django.db import migrations, models


def map_old_statuses(apps, schema_editor):
    Item = apps.get_model('catalog', 'Item')
    Item.objects.filter(status='active').update(status='approved')
    Item.objects.filter(status='moderation').update(status='pending')


def reverse_statuses(apps, schema_editor):
    Item = apps.get_model('catalog', 'Item')
    Item.objects.filter(status='approved').update(status='active')
    Item.objects.filter(status='pending').update(status='moderation')


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='favorite_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='item',
            name='min_rental_days',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='item',
            name='rejection_reason',
            field=models.TextField(blank=True, verbose_name='Причина отклонения'),
        ),
        migrations.AddField(
            model_name='item',
            name='view_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(map_old_statuses, reverse_statuses),
        migrations.AlterField(
            model_name='item',
            name='status',
            field=models.CharField(choices=[('approved', 'Одобрено'), ('pending', 'На модерации'), ('rejected', 'Отклонено'), ('inactive', 'Неактивно')], default='pending', max_length=20, verbose_name='Статус'),
        ),
    ]

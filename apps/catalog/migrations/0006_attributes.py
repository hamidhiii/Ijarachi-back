from django.db import migrations, models


def seed_category_attributes(apps, schema_editor):
    """
    Бэкофилл для БД, где категории уже существовали до появления этого поля
    (напр. staging/прод). На свежих БД категории появляются позже через
    `manage.py seed_categories`, которая сама заполняет attributes —
    единый источник данных: apps.catalog.management.commands.seed_categories.
    """
    from apps.catalog.management.commands.seed_categories import CATEGORY_ATTRIBUTES

    Category = apps.get_model('catalog', 'Category')
    for slug, attributes in CATEGORY_ATTRIBUTES.items():
        Category.objects.filter(slug=slug, attributes=[]).update(attributes=attributes)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0005_category_name_uz'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='attributes',
            field=models.JSONField(default=list, blank=True, verbose_name='Характеристики категории'),
        ),
        migrations.AddField(
            model_name='item',
            name='attributes',
            field=models.JSONField(default=dict, blank=True, verbose_name='Характеристики'),
        ),
        migrations.RunPython(seed_category_attributes, noop),
    ]

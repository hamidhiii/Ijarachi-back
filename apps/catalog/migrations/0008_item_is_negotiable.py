from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0007_item_district'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='is_negotiable',
            # False for every row that already exists: an listing published
            # before the field existed must not start advertising a haggle
            # nobody offered.
            field=models.BooleanField(default=False, verbose_name='Торг уместен'),
        ),
    ]

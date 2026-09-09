from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0006_attributes'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='district',
            field=models.CharField(blank=True, max_length=100, verbose_name='Район'),
        ),
    ]

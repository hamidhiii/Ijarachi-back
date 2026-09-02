from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0004_favorite'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='name_uz',
            field=models.CharField(blank=True, max_length=100, verbose_name='Название (uz)'),
        ),
    ]

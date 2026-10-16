from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_profile_notify_telegram'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='shop_name',
            field=models.CharField(blank=True, max_length=60, verbose_name='Название магазина / ник'),
        ),
        migrations.AddField(
            model_name='profile',
            name='about',
            field=models.TextField(blank=True, max_length=500, verbose_name='О себе'),
        ),
        migrations.AddField(
            model_name='profile',
            name='location',
            field=models.CharField(blank=True, max_length=120, verbose_name='Локация магазина'),
        ),
    ]

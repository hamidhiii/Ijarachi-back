from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='type',
            field=models.CharField(choices=[('deal', 'Deal'), ('payment', 'Payment'), ('chat', 'Chat'), ('system', 'System')], max_length=30),
        ),
    ]

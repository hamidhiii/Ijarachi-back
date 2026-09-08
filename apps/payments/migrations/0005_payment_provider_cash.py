from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0004_kyc_expense_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='payment',
            name='provider',
            field=models.CharField(
                choices=[
                    ('payme', 'Payme'),
                    ('click', 'Click'),
                    ('cash', 'Наличными при получении'),
                ],
                max_length=20,
                verbose_name='Провайдер',
            ),
        ),
    ]

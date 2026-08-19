from django.db import migrations, models


def rename_myid_expense(apps, schema_editor):
    Transaction = apps.get_model('payments', 'Transaction')
    Transaction.objects.filter(type='myid_expense').update(type='kyc_expense')


def rename_back(apps, schema_editor):
    Transaction = apps.get_model('payments', 'Transaction')
    Transaction.objects.filter(type='kyc_expense').update(type='myid_expense')


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0003_payment_url_transaction'),
    ]

    operations = [
        migrations.RunPython(rename_myid_expense, rename_back),
        migrations.AlterField(
            model_name='transaction',
            name='type',
            field=models.CharField(
                choices=[
                    ('escrow_hold', 'Escrow hold'),
                    ('refund', 'Refund'),
                    ('payout', 'Payout'),
                    ('commission', 'Commission'),
                    ('kyc_expense', 'KYC expense'),
                ],
                max_length=30,
            ),
        ),
    ]

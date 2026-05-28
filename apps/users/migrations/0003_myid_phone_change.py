import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_profile_wallet_balance'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='is_verified_myid',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='profile',
            name='myid_external_id_hash',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='profile',
            name='myid_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='MyIDVerificationAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('state', models.CharField(max_length=64, unique=True)),
                ('status', models.CharField(choices=[('started', 'Started'), ('success', 'Success'), ('failed', 'Failed')], default='started', max_length=20)),
                ('error', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='myid_attempts', to='users.customuser')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='PhoneChangeRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('new_phone', models.CharField(max_length=20)),
                ('code', models.CharField(max_length=6)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('is_used', models.BooleanField(default=False)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='phone_change_requests', to='users.customuser')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]

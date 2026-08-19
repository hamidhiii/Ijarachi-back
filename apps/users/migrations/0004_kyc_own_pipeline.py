import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_myid_phone_change'),
    ]

    operations = [
        migrations.RenameField(
            model_name='profile',
            old_name='is_verified_myid',
            new_name='is_verified_kyc',
        ),
        migrations.RenameField(
            model_name='profile',
            old_name='myid_verified_at',
            new_name='kyc_verified_at',
        ),
        migrations.RemoveField(
            model_name='profile',
            name='myid_external_id_hash',
        ),
        migrations.CreateModel(
            name='PassportDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('document_type', models.CharField(choices=[('id_card', 'ID-карта'), ('passport', 'Паспорт')], default='id_card', max_length=20, verbose_name='Тип документа')),
                ('front_image', models.ImageField(upload_to='kyc/passport/front/', verbose_name='Лицевая сторона')),
                ('back_image', models.ImageField(blank=True, null=True, upload_to='kyc/passport/back/', verbose_name='Обратная сторона')),
                ('face_image', models.ImageField(blank=True, null=True, upload_to='kyc/passport/face/', verbose_name='Фото с документа')),
                ('series', models.CharField(blank=True, max_length=10, verbose_name='Серия')),
                ('number', models.CharField(blank=True, max_length=20, verbose_name='Номер')),
                ('pinfl', models.CharField(blank=True, max_length=14, verbose_name='ПИНФЛ')),
                ('full_name', models.CharField(blank=True, max_length=200, verbose_name='ФИО (документ)')),
                ('birth_date', models.DateField(blank=True, null=True, verbose_name='Дата рождения')),
                ('issue_date', models.DateField(blank=True, null=True, verbose_name='Дата выдачи')),
                ('expiry_date', models.DateField(blank=True, null=True, verbose_name='Действителен до')),
                ('raw_ocr_text', models.TextField(blank=True, verbose_name='Распознанный текст')),
                ('face_encoding', models.JSONField(blank=True, null=True, verbose_name='Вектор лица')),
                ('status', models.CharField(choices=[('pending', 'На проверке'), ('verified', 'Подтверждён'), ('rejected', 'Отклонён')], default='pending', max_length=20, verbose_name='Статус')),
                ('reject_reason', models.TextField(blank=True, verbose_name='Причина отклонения')),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('verified_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='passport', to='users.customuser')),
            ],
            options={
                'verbose_name': 'Паспорт/ID (KYC)',
                'verbose_name_plural': 'Паспорта/ID (KYC)',
            },
        ),
        migrations.CreateModel(
            name='FaceVerification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('frame_1', models.ImageField(upload_to='kyc/face/', verbose_name='Кадр 1')),
                ('frame_2', models.ImageField(blank=True, null=True, upload_to='kyc/face/', verbose_name='Кадр 2')),
                ('frame_3', models.ImageField(blank=True, null=True, upload_to='kyc/face/', verbose_name='Кадр 3')),
                ('face_match_score', models.FloatField(blank=True, null=True, verbose_name='Схожесть лица')),
                ('face_match_passed', models.BooleanField(default=False)),
                ('liveness_score', models.FloatField(blank=True, null=True, verbose_name='Оценка живости')),
                ('liveness_passed', models.BooleanField(default=False)),
                ('status', models.CharField(choices=[('pending', 'На проверке'), ('passed', 'Пройдена'), ('failed', 'Не пройдена')], default='pending', max_length=20, verbose_name='Статус')),
                ('fail_reason', models.TextField(blank=True, verbose_name='Причина отказа')),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('verified_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='face_verification', to='users.customuser')),
            ],
            options={
                'verbose_name': 'Проверка лица (KYC)',
                'verbose_name_plural': 'Проверки лица (KYC)',
            },
        ),
        migrations.DeleteModel(
            name='MyIDVerificationAttempt',
        ),
    ]

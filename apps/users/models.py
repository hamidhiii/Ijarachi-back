from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
import hashlib


class CustomUserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError('Номер телефона обязателен')
        user = self.model(phone=phone, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(phone, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    phone = models.CharField('Телефон', max_length=20, unique=True)
    email = models.EmailField('Email', blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = CustomUserManager()

    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'

    def __str__(self):
        return self.phone


class Profile(models.Model):
    VERIFICATION_NONE = 'none'
    VERIFICATION_PENDING = 'pending'
    VERIFICATION_VERIFIED = 'verified'

    VERIFICATION_CHOICES = [
        (VERIFICATION_NONE, 'Не верифицирован'),
        (VERIFICATION_PENDING, 'На проверке'),
        (VERIFICATION_VERIFIED, 'Верифицирован'),
    ]

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='profile')
    full_name = models.CharField('ФИО', max_length=200, blank=True)
    avatar = models.ImageField('Аватар', upload_to='avatars/', blank=True, null=True)
    rating = models.FloatField('Рейтинг', default=0.0)
    rating_count = models.PositiveIntegerField('Кол-во оценок', default=0)
    wallet_balance = models.DecimalField('Баланс (сум)', max_digits=14, decimal_places=0, default=0)
    is_verified_myid = models.BooleanField(default=False)
    myid_verified_at = models.DateTimeField(null=True, blank=True)
    myid_external_id_hash = models.CharField(max_length=128, blank=True)
    verification_status = models.CharField(
        'Статус верификации',
        max_length=20,
        choices=VERIFICATION_CHOICES,
        default=VERIFICATION_NONE,
    )

    class Meta:
        verbose_name = 'Профиль'
        verbose_name_plural = 'Профили'

    def __str__(self):
        return f'Профиль — {self.user.phone}'

    def mark_myid_verified(self, external_id: str):
        self.is_verified_myid = True
        self.myid_verified_at = timezone.now()
        self.myid_external_id_hash = hashlib.sha256(external_id.encode('utf-8')).hexdigest()
        self.verification_status = self.VERIFICATION_VERIFIED
        self.save(update_fields=[
            'is_verified_myid',
            'myid_verified_at',
            'myid_external_id_hash',
            'verification_status',
        ])


class OTPCode(models.Model):
    phone = models.CharField('Телефон', max_length=20)
    code = models.CharField('OTP код', max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'OTP код'
        verbose_name_plural = 'OTP коды'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.phone} — {self.code}'


class KYCDocument(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'На проверке'),
        (STATUS_APPROVED, 'Одобрен'),
        (STATUS_REJECTED, 'Отклонён'),
    ]

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='kyc')
    doc_image = models.ImageField('Документ', upload_to='kyc/docs/')
    selfie = models.ImageField('Селфи', upload_to='kyc/selfies/')
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.TextField('Причина отклонения', blank=True)

    class Meta:
        verbose_name = 'KYC документ'
        verbose_name_plural = 'KYC документы'

    def __str__(self):
        return f'KYC — {self.user.phone} [{self.status}]'


class MyIDVerificationAttempt(models.Model):
    STATUS_STARTED = 'started'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_STARTED, 'Started'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='myid_attempts')
    state = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_STARTED)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def mark_success(self):
        self.status = self.STATUS_SUCCESS
        self.finished_at = timezone.now()
        self.save(update_fields=['status', 'finished_at'])

    def mark_failed(self, error: str):
        self.status = self.STATUS_FAILED
        self.error = error
        self.finished_at = timezone.now()
        self.save(update_fields=['status', 'error', 'finished_at'])


class PhoneChangeRequest(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='phone_change_requests')
    new_phone = models.CharField(max_length=20)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

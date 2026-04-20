from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


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

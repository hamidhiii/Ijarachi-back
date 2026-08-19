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
    is_verified_kyc = models.BooleanField(default=False)
    kyc_verified_at = models.DateTimeField(null=True, blank=True)
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

    def mark_kyc_verified(self):
        self.is_verified_kyc = True
        self.kyc_verified_at = timezone.now()
        self.verification_status = self.VERIFICATION_VERIFIED
        self.save(update_fields=[
            'is_verified_kyc',
            'kyc_verified_at',
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


class PassportDocument(models.Model):
    """
    Шаг 1 собственного KYC: скан паспорта/ID-карты Узбекистана.
    Данные (серия, номер, ПИНФЛ, ФИО, даты) извлекаются автоматически через OCR,
    а лицо с документа вырезается и кодируется для последующей сверки с селфи.
    """
    TYPE_ID_CARD = 'id_card'
    TYPE_PASSPORT = 'passport'
    TYPE_CHOICES = [
        (TYPE_ID_CARD, 'ID-карта'),
        (TYPE_PASSPORT, 'Паспорт'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_VERIFIED = 'verified'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'На проверке'),
        (STATUS_VERIFIED, 'Подтверждён'),
        (STATUS_REJECTED, 'Отклонён'),
    ]

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='passport')
    document_type = models.CharField('Тип документа', max_length=20, choices=TYPE_CHOICES, default=TYPE_ID_CARD)

    front_image = models.ImageField('Лицевая сторона', upload_to='kyc/passport/front/')
    back_image = models.ImageField('Обратная сторона', upload_to='kyc/passport/back/', blank=True, null=True)
    face_image = models.ImageField('Фото с документа', upload_to='kyc/passport/face/', blank=True, null=True)

    series = models.CharField('Серия', max_length=10, blank=True)
    number = models.CharField('Номер', max_length=20, blank=True)
    pinfl = models.CharField('ПИНФЛ', max_length=14, blank=True)
    full_name = models.CharField('ФИО (документ)', max_length=200, blank=True)
    birth_date = models.DateField('Дата рождения', null=True, blank=True)
    issue_date = models.DateField('Дата выдачи', null=True, blank=True)
    expiry_date = models.DateField('Действителен до', null=True, blank=True)
    raw_ocr_text = models.TextField('Распознанный текст', blank=True)

    # 128-мерный вектор лица (face_recognition), сериализованный в JSON, для сверки с селфи.
    face_encoding = models.JSONField('Вектор лица', null=True, blank=True)

    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reject_reason = models.TextField('Причина отклонения', blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Паспорт/ID (KYC)'
        verbose_name_plural = 'Паспорта/ID (KYC)'

    def __str__(self):
        return f'Документ — {self.user.phone} [{self.status}]'

    def mark_verified(self):
        self.status = self.STATUS_VERIFIED
        self.verified_at = timezone.now()
        self.reject_reason = ''
        self.save(update_fields=['status', 'verified_at', 'reject_reason'])

    def mark_rejected(self, reason: str):
        self.status = self.STATUS_REJECTED
        self.reject_reason = reason
        self.save(update_fields=['status', 'reject_reason'])


class FaceVerification(models.Model):
    """
    Шаг 2 собственного KYC: селфи клиента сверяется с лицом на документе (face match)
    и проверяется на «живость» (liveness) по нескольким кадрам, снятым с камеры.
    """
    STATUS_PENDING = 'pending'
    STATUS_PASSED = 'passed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'На проверке'),
        (STATUS_PASSED, 'Пройдена'),
        (STATUS_FAILED, 'Не пройдена'),
    ]

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='face_verification')

    # Один обязательный кадр + до двух дополнительных (для проверки живости по морганию/повороту).
    frame_1 = models.ImageField('Кадр 1', upload_to='kyc/face/')
    frame_2 = models.ImageField('Кадр 2', upload_to='kyc/face/', blank=True, null=True)
    frame_3 = models.ImageField('Кадр 3', upload_to='kyc/face/', blank=True, null=True)

    face_match_score = models.FloatField('Схожесть лица', null=True, blank=True)
    face_match_passed = models.BooleanField(default=False)
    liveness_score = models.FloatField('Оценка живости', null=True, blank=True)
    liveness_passed = models.BooleanField(default=False)

    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    fail_reason = models.TextField('Причина отказа', blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Проверка лица (KYC)'
        verbose_name_plural = 'Проверки лица (KYC)'

    def __str__(self):
        return f'Лицо — {self.user.phone} [{self.status}]'

    def mark_passed(self, match_score: float, liveness_score: float):
        self.status = self.STATUS_PASSED
        self.face_match_score = match_score
        self.face_match_passed = True
        self.liveness_score = liveness_score
        self.liveness_passed = True
        self.fail_reason = ''
        self.verified_at = timezone.now()
        self.save(update_fields=[
            'status', 'face_match_score', 'face_match_passed',
            'liveness_score', 'liveness_passed', 'fail_reason', 'verified_at',
        ])

    def mark_failed(self, reason: str, match_score: float = None, liveness_score: float = None,
                     face_match_passed: bool = False, liveness_passed: bool = False):
        self.status = self.STATUS_FAILED
        self.fail_reason = reason
        self.face_match_score = match_score
        self.face_match_passed = face_match_passed
        self.liveness_score = liveness_score
        self.liveness_passed = liveness_passed
        self.save(update_fields=[
            'status', 'fail_reason', 'face_match_score', 'face_match_passed',
            'liveness_score', 'liveness_passed',
        ])


class PhoneChangeRequest(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='phone_change_requests')
    new_phone = models.CharField(max_length=20)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']


class TelegramLink(models.Model):
    """
    Связка номера телефона с чатом Telegram-бота: пользователь подтверждает номер,
    поделившись контактом с ботом, после чего OTP-коды на этот номер шлём в Telegram
    вместо SMS (временное решение вместо Eskiz.uz).
    """
    phone = models.CharField('Телефон', max_length=20, unique=True)
    chat_id = models.BigIntegerField('Telegram chat_id')
    telegram_user_id = models.BigIntegerField('Telegram user_id', null=True, blank=True)
    username = models.CharField('Telegram username', max_length=64, blank=True)
    linked_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Привязка Telegram'
        verbose_name_plural = 'Привязки Telegram'

    def __str__(self):
        return f'{self.phone} -> chat {self.chat_id}'

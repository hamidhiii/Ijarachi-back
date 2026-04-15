from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class CustomUserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError(_('Phone number is required'))
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
    phone = models.CharField(_('Phone'), max_length=20, unique=True)
    email = models.EmailField(_('Email'), blank=True)
    is_active = models.BooleanField(_('Active'), default=True)
    is_staff = models.BooleanField(_('Staff status'), default=False)
    date_joined = models.DateTimeField(_('Date joined'), default=timezone.now)

    objects = CustomUserManager()

    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _('User')
        verbose_name_plural = _('Users')

    def __str__(self):
        return self.phone


class Profile(models.Model):
    VERIFICATION_NONE = 'none'
    VERIFICATION_PENDING = 'pending'
    VERIFICATION_VERIFIED = 'verified'

    VERIFICATION_CHOICES = [
        (VERIFICATION_NONE, _('Not verified')),
        (VERIFICATION_PENDING, _('Pending review')),
        (VERIFICATION_VERIFIED, _('Verified')),
    ]

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='profile')
    full_name = models.CharField(_('Full Name'), max_length=200, blank=True)
    avatar = models.ImageField(_('Avatar'), upload_to='avatars/', blank=True, null=True)
    rating = models.FloatField(_('Rating'), default=0.0)
    rating_count = models.PositiveIntegerField(_('Rating count'), default=0)
    verification_status = models.CharField(
        _('Verification status'),
        max_length=20,
        choices=VERIFICATION_CHOICES,
        default=VERIFICATION_NONE,
    )
    
    # New fields for mobile app
    fcm_token = models.CharField(_('FCM Token'), max_length=255, blank=True, null=True)
    language = models.CharField(_('Language'), max_length=10, default='ru', choices=[
        ('ru', _('Russian')),
        ('uz', _('Uzbek')),
        ('en', _('English')),
    ])

    class Meta:
        verbose_name = _('Profile')
        verbose_name_plural = _('Profiles')

    def __str__(self):
        return f'Profile — {self.user.phone}'


class OTPCode(models.Model):
    phone = models.CharField(_('Phone'), max_length=20)
    code = models.CharField(_('OTP code'), max_length=6)
    created_at = models.DateTimeField(_('Created at'), auto_now_add=True)
    is_used = models.BooleanField(_('Used'), default=False)

    class Meta:
        verbose_name = _('OTP code')
        verbose_name_plural = _('OTP codes')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.phone} — {self.code}'


class KYCDocument(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_PENDING, _('Pending review')),
        (STATUS_APPROVED, _('Approved')),
        (STATUS_REJECTED, _('Rejected')),
    ]

    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='kyc')
    doc_image = models.ImageField(_('Document image'), upload_to='kyc/docs/')
    selfie = models.ImageField(_('Selfie'), upload_to='kyc/selfies/')
    status = models.CharField(_('Status'), max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    submitted_at = models.DateTimeField(_('Submitted at'), auto_now_add=True)
    reviewed_at = models.DateTimeField(_('Reviewed at'), null=True, blank=True)
    reject_reason = models.TextField(_('Rejection reason'), blank=True)

    class Meta:
        verbose_name = _('KYC document')
        verbose_name_plural = _('KYC documents')

    def __str__(self):
        return f'KYC — {self.user.phone} [{self.status}]'

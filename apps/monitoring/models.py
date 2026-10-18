from django.conf import settings
from django.db import models


class MonitorAccess(models.Model):
    """
    Доступ сотрудника к монитору. Отдельная сущность, а не права Django:
    монитор — не админка, набор его разделов свой, и выдаёт их суперюзер
    вручную. Суперюзеру запись не нужна, он видит всё (см. access.py).
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='monitor_access',
        verbose_name='Пользователь',
    )
    is_active = models.BooleanField('Доступ включён', default=True)

    can_view_deals = models.BooleanField('Сделки', default=True)
    can_view_disputes = models.BooleanField('Споры', default=True)
    can_view_kyc = models.BooleanField('KYC', default=False)
    can_view_payments = models.BooleanField('Платежи', default=False)
    can_view_errors = models.BooleanField('Ошибки', default=True)
    can_manage_access = models.BooleanField('Управление доступами', default=False)

    note = models.CharField('Заметка', max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='granted_monitor_access',
        verbose_name='Кем выдан',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Суперюзеру соответствует SuperuserAccess из access.py; у обычного доступа
    # флаг всегда False — шаблоны по нему решают, показывать ли ссылки в админку.
    is_superuser = False

    class Meta:
        verbose_name = 'Доступ к монитору'
        verbose_name_plural = 'Доступы к монитору'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.phone} — монитор'

    @property
    def sections(self):
        """Названия открытых разделов — для списка доступов."""
        labels = [
            (self.can_view_deals, 'Сделки'),
            (self.can_view_disputes, 'Споры'),
            (self.can_view_kyc, 'KYC'),
            (self.can_view_payments, 'Платежи'),
            (self.can_view_errors, 'Ошибки'),
            (self.can_manage_access, 'Доступы'),
        ]
        return [label for granted, label in labels if granted]


class AuthEvent(models.Model):
    """
    Журнал шагов входа и регистрации: кто пришёл, дошёл ли до кода, где споткнулся.
    Пишется из auth-вью и с фронта через /api/v1/analytics/track/. Сбой записи
    никогда не ломает вход (см. events.record).
    """
    VISIT = 'visit'
    AUTH_OPENED = 'auth_opened'
    PHONE_ENTERED = 'phone_entered'
    CLIENT_ERROR = 'client_error'
    OTP_SENT = 'otp_sent'
    OTP_TELEGRAM_REQUIRED = 'otp_telegram_required'
    OTP_COOLDOWN = 'otp_cooldown'
    OTP_SEND_FAILED = 'otp_send_failed'
    OTP_INVALID_INPUT = 'otp_invalid_input'
    VERIFY_FAILED = 'verify_failed'
    VERIFY_INVALID_INPUT = 'verify_invalid_input'
    LOGIN_OK = 'login_ok'
    REGISTER_OK = 'register_ok'

    # События, которые разрешено слать с фронта; остальные — только из бэкенда.
    CLIENT_EVENTS = (VISIT, AUTH_OPENED, PHONE_ENTERED, CLIENT_ERROR)

    EVENT_CHOICES = [
        (VISIT, 'Зашёл на сайт'),
        (AUTH_OPENED, 'Открыл форму входа'),
        (PHONE_ENTERED, 'Ввёл номер'),
        (CLIENT_ERROR, 'Ошибка на странице'),
        (OTP_SENT, 'Код отправлен'),
        (OTP_TELEGRAM_REQUIRED, 'Нужно подтвердить Telegram'),
        (OTP_COOLDOWN, 'Слишком частый запрос кода'),
        (OTP_SEND_FAILED, 'Код не удалось отправить'),
        (OTP_INVALID_INPUT, 'Неверный номер телефона'),
        (VERIFY_FAILED, 'Неверный или устаревший код'),
        (VERIFY_INVALID_INPUT, 'Некорректный ввод кода'),
        (LOGIN_OK, 'Вошёл'),
        (REGISTER_OK, 'Зарегистрировался'),
    ]
    # Шаги, после которых человек точно что-то делал в форме входа.
    OTP_ACTIVITY = (AUTH_OPENED, PHONE_ENTERED, OTP_SENT, OTP_TELEGRAM_REQUIRED, OTP_COOLDOWN,
                    OTP_SEND_FAILED, OTP_INVALID_INPUT, VERIFY_FAILED, VERIFY_INVALID_INPUT,
                    LOGIN_OK, REGISTER_OK)
    FAILURE_EVENTS = (
        OTP_TELEGRAM_REQUIRED, OTP_COOLDOWN, OTP_SEND_FAILED, OTP_INVALID_INPUT,
        VERIFY_FAILED, VERIFY_INVALID_INPUT, CLIENT_ERROR,
    )

    event = models.CharField('Событие', max_length=30, choices=EVENT_CHOICES)
    phone = models.CharField('Телефон', max_length=20, blank=True)
    visitor_id = models.CharField('Посетитель', max_length=64, blank=True, db_index=True)
    ip = models.GenericIPAddressField('IP', null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)
    detail = models.CharField('Подробности', max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Событие входа'
        verbose_name_plural = 'События входа'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['event', 'created_at'], name='authevent_event_created_idx')]

    def __str__(self):
        return f'{self.get_event_display()} {self.phone or self.visitor_id}'

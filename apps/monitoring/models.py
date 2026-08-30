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

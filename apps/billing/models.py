"""
Платные тарифы для прокатов (решение 16.11.2026).

Plan — справочник тарифов (FREE, START, BUSINESS, PRO): цена за месяц, лимит
объявлений и права. Строки создаёт миграция, цены и права правятся в админке.

Subscription — текущее состояние тарифа пользователя, одна строка на
пользователя. Тариф действует, пока ends_at в будущем; после — пользователь на
FREE (строку не удаляем, по ней видно, что было). SubscriptionPeriod — история:
каждый оплаченный или выданный вручную период отдельной строкой, по ней
считаются отток и список подписок в админке.
"""
from django.conf import settings
from django.db import models


class Plan(models.Model):
    FREE = 'free'
    START = 'start'
    BUSINESS = 'business'
    PRO = 'pro'

    CODE_CHOICES = [
        (FREE, 'FREE'),
        (START, 'START'),
        (BUSINESS, 'BUSINESS'),
        (PRO, 'PRO'),
    ]

    code = models.CharField('Код', max_length=20, choices=CODE_CHOICES, unique=True)
    name = models.CharField('Название', max_length=50)
    price = models.DecimalField('Цена за месяц (сум)', max_digits=12, decimal_places=0, default=0)
    # Пусто — без лимита (PRO).
    listing_limit = models.PositiveIntegerField('Лимит активных объявлений', null=True, blank=True)
    search_priority = models.BooleanField('Приоритет в выдаче', default=False)
    staff_access = models.BooleanField('Сотрудники в кабинете', default=False)
    statistics = models.BooleanField('Статистика', default=False)
    branches = models.BooleanField('Несколько точек (филиалы)', default=False)
    data_export = models.BooleanField('Выгрузка CSV/XLSX', default=False)
    # Порядок тарифов: выше — дороже. По нему решается, повышение это или понижение.
    rank = models.PositiveSmallIntegerField('Ступень', default=0)
    is_active = models.BooleanField('Продаётся', default=True)

    class Meta:
        verbose_name = 'Тариф'
        verbose_name_plural = 'Тарифы'
        ordering = ['rank']

    def __str__(self):
        return self.name

    @property
    def is_paid(self):
        return self.code != self.FREE


class Subscription(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='subscription', verbose_name='Пользователь',
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='subscriptions', verbose_name='Тариф')
    ends_at = models.DateTimeField('Действует до')
    # Окончание обработано (лишние объявления сняты, пользователь уведомлён) —
    # для какого ends_at. Продление меняет ends_at, и всё сбрасывается само.
    expiry_processed_for = models.DateTimeField(null=True, blank=True, editable=False)
    reminder_3d_sent_for = models.DateTimeField(null=True, blank=True, editable=False)
    reminder_last_day_sent_for = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Подписка'
        verbose_name_plural = 'Подписки'
        ordering = ['-ends_at']
        indexes = [models.Index(fields=['ends_at'])]

    def __str__(self):
        return f'{self.user} — {self.plan} до {self.ends_at:%d.%m.%Y}'


class SubscriptionPeriod(models.Model):
    SOURCE_PAYMENT = 'payment'
    SOURCE_MANUAL = 'manual'
    SOURCE_CHOICES = [
        (SOURCE_PAYMENT, 'Оплата'),
        (SOURCE_MANUAL, 'Вручную (сотрудник)'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='subscription_periods', verbose_name='Пользователь',
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='periods', verbose_name='Тариф')
    starts_at = models.DateTimeField('Начало')
    ends_at = models.DateTimeField('Окончание')
    source = models.CharField('Источник', max_length=20, choices=SOURCE_CHOICES)
    amount = models.DecimalField('Сумма (сум)', max_digits=12, decimal_places=0, default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='Кто выдал',
    )
    comment = models.CharField('Комментарий', max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Период подписки'
        verbose_name_plural = 'Периоды подписки'
        ordering = ['-starts_at']
        indexes = [models.Index(fields=['starts_at', 'ends_at'])]

    def __str__(self):
        return f'{self.user} — {self.plan} {self.starts_at:%d.%m.%Y}–{self.ends_at:%d.%m.%Y}'

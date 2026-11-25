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
    # Кабинет owner.rentoo.uz: брони, склад, клиенты, напоминания и бот (START+).
    crm = models.BooleanField('CRM (кабинет)', default=False)
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
    # Подарок по акции (apps.billing.promo) — не оплата: в платящих и MRR не считается.
    SOURCE_PROMO = 'promo'
    SOURCE_CHOICES = [
        (SOURCE_PAYMENT, 'Оплата'),
        (SOURCE_MANUAL, 'Вручную (сотрудник)'),
        (SOURCE_PROMO, 'Акция'),
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


class BillingOrder(models.Model):
    """
    Заказ на разовую оплату: месяц тарифа или продвижение объявления.

    Оплата — Click или Payme (заглушка при PAYMENTS_MODE=stub). Состояние
    транзакции провайдера хранится здесь же: у заказа одна транзакция, после
    отмены заказ закрыт, и для новой попытки создаётся новый заказ.
    """
    KIND_PLAN = 'plan'
    KIND_PROMOTION = 'promotion'
    KIND_CHOICES = [
        (KIND_PLAN, 'Тариф'),
        (KIND_PROMOTION, 'Продвижение'),
    ]

    PROMO_TOP = 'top'
    PROMO_VIP = 'vip'
    PROMO_CHOICES = [
        (PROMO_TOP, 'Поднять в топ'),
        (PROMO_VIP, 'VIP'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_PAID = 'paid'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Ждёт оплаты'),
        (STATUS_PAID, 'Оплачен'),
        (STATUS_CANCELLED, 'Отменён'),
    ]

    PROVIDER_CLICK = 'click'
    PROVIDER_PAYME = 'payme'
    # PAYMENTS_MODE=stub (только dev/staging): заказ оплачен без денег.
    PROVIDER_STUB = 'stub'
    PROVIDER_CHOICES = [
        (PROVIDER_CLICK, 'Click'),
        (PROVIDER_PAYME, 'Payme'),
        (PROVIDER_STUB, 'Заглушка (тест)'),
    ]

    # Состояния транзакции Payme (Merchant API).
    PAYME_CREATED = 1
    PAYME_PERFORMED = 2
    PAYME_CANCELLED = -1
    PAYME_CANCELLED_AFTER_PERFORM = -2

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='billing_orders', verbose_name='Пользователь',
    )
    kind = models.CharField('Что оплачивается', max_length=20, choices=KIND_CHOICES)
    plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT, null=True, blank=True,
        related_name='orders', verbose_name='Тариф',
    )
    promotion = models.CharField('Продвижение', max_length=10, choices=PROMO_CHOICES, blank=True)
    item = models.ForeignKey(
        'catalog.Item', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='billing_orders', verbose_name='Объявление',
    )
    amount = models.DecimalField('Сумма (сум)', max_digits=12, decimal_places=0)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    provider = models.CharField('Провайдер', max_length=20, choices=PROVIDER_CHOICES)
    # Payme: id транзакции; Click: click_trans_id.
    provider_transaction_id = models.CharField('ID транзакции провайдера', max_length=100, blank=True, db_index=True)
    provider_state = models.SmallIntegerField('Состояние транзакции', default=0)
    # Метки Payme в миллисекундах — их же возвращаем в ответах.
    provider_create_time = models.BigIntegerField(null=True, blank=True)
    provider_perform_time = models.BigIntegerField(null=True, blank=True)
    provider_cancel_time = models.BigIntegerField(null=True, blank=True)
    cancel_reason = models.SmallIntegerField(null=True, blank=True)
    raw = models.JSONField('Данные провайдера', default=dict, blank=True)
    # Оплата прошла, но применить её не получилось (например, тариф ниже уже
    # действующего) — нужен сотрудник.
    needs_attention = models.CharField('Требует внимания', max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField('Оплачен', null=True, blank=True)

    class Meta:
        verbose_name = 'Заказ (оплата)'
        verbose_name_plural = 'Заказы (оплаты)'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'provider_transaction_id'],
                condition=~models.Q(provider_transaction_id=''),
                name='billing_order_unique_provider_tx',
            ),
        ]

    def __str__(self):
        return f'Заказ #{self.pk} {self.get_kind_display()} {self.amount} — {self.get_status_display()}'

    @property
    def amount_tiyin(self):
        return int(self.amount) * 100

    @property
    def title(self):
        if self.kind == self.KIND_PLAN and self.plan_id:
            return f'Тариф {self.plan.name} на {settings.BILLING_PERIOD_DAYS} дней'
        return f'{self.get_promotion_display()}: «{self.item.title if self.item else "объявление"}»'


class Promotion(models.Model):
    """
    История продвижения объявления: каждая оплата — строка. Действующее
    состояние — Item.top_until / Item.vip_until, по ним сортируется выдача.
    """
    item = models.ForeignKey('catalog.Item', on_delete=models.CASCADE, related_name='promotions', verbose_name='Объявление')
    kind = models.CharField('Вид', max_length=10, choices=BillingOrder.PROMO_CHOICES)
    starts_at = models.DateTimeField('Начало')
    ends_at = models.DateTimeField('Окончание')
    order = models.OneToOneField(
        BillingOrder, on_delete=models.PROTECT, null=True, blank=True,
        related_name='promotion_record', verbose_name='Заказ',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Продвижение'
        verbose_name_plural = 'Продвижения'
        ordering = ['-starts_at']

    def __str__(self):
        return f'{self.get_kind_display()} #{self.item_id} до {self.ends_at:%d.%m.%Y}'

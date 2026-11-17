from django.db import models
from django.conf import settings


class Payment(models.Model):
    PROVIDER_PAYME = 'payme'
    PROVIDER_CLICK = 'click'
    PROVIDER_CASH = 'cash'
    # Заглушка онлайн-оплаты (PAYMENTS_MODE=stub, только dev/staging): денег не
    # было, отдельный провайдер — чтобы такие платежи не путались с настоящими.
    PROVIDER_STUB = 'stub'

    PROVIDER_CHOICES = [
        (PROVIDER_PAYME, 'Payme'),
        (PROVIDER_CLICK, 'Click'),
        (PROVIDER_CASH, 'Наличными при получении'),
        (PROVIDER_STUB, 'Заглушка (тест)'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_PAID = 'paid'
    STATUS_FAILED = 'failed'
    STATUS_REFUNDED = 'refunded'
    STATUS_COMPLETED = 'completed'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Ожидает'),
        (STATUS_PAID, 'Оплачено (эскроу)'),
        (STATUS_FAILED, 'Ошибка'),
        (STATUS_REFUNDED, 'Возвращено'),
        (STATUS_COMPLETED, 'Выплачено владельцу'),
    ]

    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.PROTECT,
        related_name='payments',
        verbose_name='Бронирование',
    )
    provider = models.CharField('Провайдер', max_length=20, choices=PROVIDER_CHOICES)
    amount = models.DecimalField('Сумма (тийин)', max_digits=14, decimal_places=0)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    provider_transaction_id = models.CharField('ID транзакции провайдера', max_length=200, blank=True)
    payment_url = models.CharField(max_length=500, blank=True)
    raw_request = models.JSONField('Сырой запрос webhook', default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Платёж'
        verbose_name_plural = 'Платежи'
        ordering = ['-created_at']

    def __str__(self):
        return f'Платёж #{self.pk} [{self.provider}] — {self.status}'


class Transaction(models.Model):
    TYPE_ESCROW_HOLD = 'escrow_hold'
    TYPE_REFUND = 'refund'
    TYPE_PAYOUT = 'payout'
    TYPE_COMMISSION = 'commission'
    TYPE_KYC_EXPENSE = 'kyc_expense'

    TYPE_CHOICES = [
        (TYPE_ESCROW_HOLD, 'Escrow hold'),
        (TYPE_REFUND, 'Refund'),
        (TYPE_PAYOUT, 'Payout'),
        (TYPE_COMMISSION, 'Commission'),
        (TYPE_KYC_EXPENSE, 'KYC expense'),
    ]

    booking = models.ForeignKey('bookings.Booking', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=14, decimal_places=0)
    currency = models.CharField(max_length=3, default='UZS')
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.type} {self.amount} {self.currency}'


class WalletTransaction(models.Model):
    """
    Движение по внутреннему кошельку (Profile.wallet_balance). Баланс меняется
    только через apps.payments.wallet.credit_wallet, который пишет и эту строку:
    у каждого изменения баланса есть тип, сделка и время.
    """
    TYPE_RENT_PAYOUT = 'rent_payout'
    TYPE_DEPOSIT_REFUND = 'deposit_refund'
    TYPE_DEPOSIT_COMPENSATION = 'deposit_compensation'
    TYPE_ADJUSTMENT = 'adjustment'

    TYPE_CHOICES = [
        (TYPE_RENT_PAYOUT, 'Выплата за аренду'),
        (TYPE_DEPOSIT_REFUND, 'Возврат залога'),
        (TYPE_DEPOSIT_COMPENSATION, 'Удержанный залог в пользу владельца'),
        (TYPE_ADJUSTMENT, 'Ручная корректировка'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='wallet_transactions', verbose_name='Пользователь',
    )
    type = models.CharField('Тип', max_length=30, choices=TYPE_CHOICES)
    amount = models.DecimalField('Сумма (сум)', max_digits=14, decimal_places=0)
    balance_after = models.DecimalField('Баланс после (сум)', max_digits=14, decimal_places=0)
    booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.PROTECT, null=True, blank=True,
        related_name='wallet_transactions', verbose_name='Сделка',
    )
    comment = models.CharField('Комментарий', max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Операция кошелька'
        verbose_name_plural = 'Операции кошелька'
        ordering = ['-created_at']
        constraints = [
            # Один и тот же вид начисления по одной сделке одному человеку — один
            # раз. Защита от двойной выплаты на уровне БД, если два release_escrow
            # всё-таки разминутся с блокировками.
            models.UniqueConstraint(
                fields=['booking', 'type', 'user'],
                condition=models.Q(booking__isnull=False),
                name='wallet_tx_once_per_booking',
            ),
        ]

    def __str__(self):
        return f'{self.get_type_display()} {self.amount} → {self.user_id}'

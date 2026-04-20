from django.db import models
from django.conf import settings


class Payment(models.Model):
    PROVIDER_PAYME = 'payme'
    PROVIDER_CLICK = 'click'

    PROVIDER_CHOICES = [
        (PROVIDER_PAYME, 'Payme'),
        (PROVIDER_CLICK, 'Click'),
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
    raw_request = models.JSONField('Сырой запрос webhook', default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Платёж'
        verbose_name_plural = 'Платежи'
        ordering = ['-created_at']

    def __str__(self):
        return f'Платёж #{self.pk} [{self.provider}] — {self.status}'

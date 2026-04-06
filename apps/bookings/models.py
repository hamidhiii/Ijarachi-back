from django.db import models
from django.conf import settings
from django.utils import timezone


class Booking(models.Model):
    STATUS_CREATED = 'created'
    STATUS_WAITING_PAYMENT = 'waiting_payment'
    STATUS_PAID_ESCROW = 'paid_escrow'
    STATUS_ACTIVE = 'active'
    STATUS_RETURNING = 'returning'
    STATUS_COMPLETED = 'completed'
    STATUS_DISPUTE = 'dispute'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_CREATED, 'Создано'),
        (STATUS_WAITING_PAYMENT, 'Ожидает оплаты'),
        (STATUS_PAID_ESCROW, 'Оплачено (эскроу)'),
        (STATUS_ACTIVE, 'Активно (вещь у арендатора)'),
        (STATUS_RETURNING, 'Возврат'),
        (STATUS_COMPLETED, 'Завершено'),
        (STATUS_DISPUTE, 'Спор'),
        (STATUS_CANCELLED, 'Отменено'),
    ]

    item = models.ForeignKey(
        'catalog.Item',
        on_delete=models.PROTECT,
        related_name='bookings',
        verbose_name='Вещь',
    )
    renter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='rentals',
        verbose_name='Арендатор',
    )
    start_date = models.DateField('Дата начала')
    end_date = models.DateField('Дата окончания')

    # Pricing snapshot at booking time
    price_per_day = models.DecimalField('Цена/день', max_digits=12, decimal_places=0)
    deposit_amount = models.DecimalField('Залог', max_digits=12, decimal_places=0)
    commission_amount = models.DecimalField('Комиссия платформы', max_digits=12, decimal_places=0)
    total_price = models.DecimalField('Итого', max_digits=12, decimal_places=0)

    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_CREATED)
    renter_comment = models.TextField('Комментарий арендатора', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Бронирование'
        verbose_name_plural = 'Бронирования'
        ordering = ['-created_at']

    def __str__(self):
        return f'Бронь #{self.pk} — {self.item.title} [{self.status}]'

    @property
    def days(self):
        return (self.end_date - self.start_date).days + 1

    def transition_to(self, new_status: str):
        """Update status and log the change."""
        import logging
        logger = logging.getLogger('apps.bookings')
        old = self.status
        self.status = new_status
        self.save(update_fields=['status', 'updated_at'])
        logger.info('Booking #%s: %s → %s', self.pk, old, new_status)


class PhotoProtocol(models.Model):
    TYPE_BEFORE = 'before'
    TYPE_AFTER = 'after'

    TYPE_CHOICES = [
        (TYPE_BEFORE, 'До передачи'),
        (TYPE_AFTER, 'После возврата'),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='photos', verbose_name='Бронирование')
    photo_type = models.CharField('Тип', max_length=10, choices=TYPE_CHOICES)
    image = models.ImageField('Фото', upload_to='protocols/')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='uploaded_photos',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    comment = models.TextField('Комментарий', blank=True)

    class Meta:
        verbose_name = 'Фотопротокол'
        verbose_name_plural = 'Фотопротоколы'
        ordering = ['uploaded_at']

    def __str__(self):
        return f'Фото [{self.photo_type}] — Бронь #{self.booking_id}'

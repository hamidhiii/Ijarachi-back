from django.db import models
from django.conf import settings
from django.utils import timezone


class Booking(models.Model):
    STATUS_CREATED = 'created'
    STATUS_WAITING_OWNER = 'waiting_owner'
    STATUS_WAITING_RENTER = 'waiting_renter'
    STATUS_IN_RENT = 'in_rent'
    STATUS_RETURNING = 'returning'
    STATUS_INSPECTION = 'inspection'
    STATUS_COMPLETED = 'completed'
    STATUS_DISPUTE = 'dispute'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_CREATED, 'Оплачено (Эскроу)'),
        (STATUS_WAITING_OWNER, 'Ожидает 5 фото от владельца'),
        (STATUS_WAITING_RENTER, 'Ожидает 5 фото и подтверждения от арендатора'),
        (STATUS_IN_RENT, 'Активная аренда'),
        (STATUS_RETURNING, 'Возвращается (получены фото ПОСЛЕ от арендатора)'),
        (STATUS_INSPECTION, 'Проверка (24ч у владельца)'),
        (STATUS_COMPLETED, 'Завершено (деньги выплачиваются)'),
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

    # Pricing
    price_per_day = models.DecimalField('Цена за сутки (владельца)', max_digits=12, decimal_places=0)
    commission_amount = models.DecimalField('Комиссия платформы (15%)', max_digits=12, decimal_places=0)
    total_price = models.DecimalField('Итого к оплате (арендатором)', max_digits=12, decimal_places=0)

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


class VerificationPhoto(models.Model):
    TYPE_OWNER_START = 'owner_start'
    TYPE_RENTER_START = 'renter_start'
    TYPE_RENTER_END = 'renter_end'
    TYPE_OWNER_END = 'owner_end'

    TYPE_CHOICES = [
        (TYPE_OWNER_START, 'Владелец: До передачи'),
        (TYPE_RENTER_START, 'Арендатор: До получения'),
        (TYPE_RENTER_END, 'Арендатор: После возврата'),
        (TYPE_OWNER_END, 'Владелец: После получения'),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='verification_photos', verbose_name='Бронирование')
    photo_type = models.CharField('Тип протокола', max_length=20, choices=TYPE_CHOICES)
    image = models.ImageField('Фотография', upload_to='verifications/')
    
    file_hash = models.CharField('SHA-256 Хэш', max_length=64, help_text='Хэш для защиты от подмены')
    metadata = models.JSONField('Метаданные (GPS, Device, Time)', default=dict)
    
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='uploaded_verifications',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    comment = models.TextField('Комментарий', blank=True)

    class Meta:
        verbose_name = 'Фото верификации'
        verbose_name_plural = 'Фото верификации'
        ordering = ['uploaded_at']

    def __str__(self):
        return f'Верификация [{self.photo_type}] — Бронь #{self.booking_id}'

from django.db import models
from django.conf import settings


class Deliverer(models.Model):
    name = models.CharField('Имя', max_length=100)
    phone = models.CharField('Телефон', max_length=20)
    is_active = models.BooleanField('Активен', default=True)

    class Meta:
        verbose_name = 'Доставщик'
        verbose_name_plural = 'Доставщики'

    def __str__(self):
        return f'{self.name} ({self.phone})'


class Booking(models.Model):
    # Payment pending — internal state before payment confirmed
    STATUS_PAYMENT_PENDING = 'payment_pending'
    # Progress visible to users
    STATUS_PLACED = 'placed'               # Заказ оформлен
    STATUS_PICKUP_SCHEDULED = 'pickup_scheduled'  # Доставщик едет к владельцу
    STATUS_PICKED_UP = 'picked_up'         # Доставщик забрал вещь
    STATUS_ACTIVE = 'active'               # Аренда активна (доставлено арендатору)
    STATUS_COMPLETED = 'completed'         # Аренда завершена
    STATUS_CANCELLED = 'cancelled'         # Отменено

    STATUS_CHOICES = [
        (STATUS_PAYMENT_PENDING, 'Ожидает оплаты'),
        (STATUS_PLACED, 'Заказ оформлен'),
        (STATUS_PICKUP_SCHEDULED, 'Доставщик едет к владельцу'),
        (STATUS_PICKED_UP, 'Доставщик забрал вещь'),
        (STATUS_ACTIVE, 'Аренда активна'),
        (STATUS_COMPLETED, 'Аренда завершена'),
        (STATUS_CANCELLED, 'Отменено'),
    ]

    # Progress label per status for each role (used by mobile)
    PROGRESS_RENTER = {
        STATUS_PAYMENT_PENDING: 'Ожидание подтверждения оплаты',
        STATUS_PLACED: 'Заказ оформлен',
        STATUS_PICKUP_SCHEDULED: 'Доставщик заберёт вещь у владельца',
        STATUS_PICKED_UP: 'Доставщик забрал вещь, скоро привезёт',
        STATUS_ACTIVE: 'Аренда началась',
        STATUS_COMPLETED: 'Аренда завершена',
        STATUS_CANCELLED: 'Заказ отменён',
    }

    PROGRESS_OWNER = {
        STATUS_PAYMENT_PENDING: 'Новый заказ — ожидание оплаты',
        STATUS_PLACED: 'Новый заказ — данные заказа ниже',
        STATUS_PICKUP_SCHEDULED: 'Доставщик едет к вам',
        STATUS_PICKED_UP: 'Доставщик везёт вещь арендатору',
        STATUS_ACTIVE: 'Аренда активна',
        STATUS_COMPLETED: 'Аренда завершена, средства зачислены',
        STATUS_CANCELLED: 'Заказ отменён',
    }

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
    commission_amount = models.DecimalField('Комиссия платформы (15%)', max_digits=12, decimal_places=0)
    total_price = models.DecimalField('Итого', max_digits=12, decimal_places=0)

    # Delivery
    delivery_address = models.CharField('Адрес доставки', max_length=500, blank=True, default='')
    delivery_lat = models.FloatField('Широта доставки', null=True, blank=True)
    delivery_lng = models.FloatField('Долгота доставки', null=True, blank=True)
    deliverer = models.ForeignKey(
        Deliverer,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='deliveries',
        verbose_name='Доставщик',
    )
    pickup_eta = models.DateTimeField('ETA к владельцу', null=True, blank=True)
    delivery_eta = models.DateTimeField('ETA к арендатору', null=True, blank=True)

    status = models.CharField('Статус', max_length=30, choices=STATUS_CHOICES, default=STATUS_PAYMENT_PENDING)
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
        import logging
        logger = logging.getLogger('apps.bookings')
        old = self.status
        self.status = new_status
        self.save(update_fields=['status', 'updated_at'])
        logger.info('Booking #%s: %s → %s', self.pk, old, new_status)

    def progress_for(self, role: str) -> str:
        """Returns human-readable progress label for 'renter' or 'owner'."""
        mapping = self.PROGRESS_RENTER if role == 'renter' else self.PROGRESS_OWNER
        return mapping.get(self.status, self.status)

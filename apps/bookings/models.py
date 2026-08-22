from django.conf import settings
from django.db import models


class Booking(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_PENDING_PAYMENT = 'pending_payment'
    STATUS_PAID = 'paid'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_RETURNED = 'returned'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_DISPUTED = 'disputed'

    # Backward-compatible aliases used by older endpoints.
    STATUS_PAYMENT_PENDING = STATUS_PENDING_PAYMENT
    STATUS_PLACED = STATUS_PAID
    STATUS_PICKUP_SCHEDULED = STATUS_IN_PROGRESS
    STATUS_PICKED_UP = STATUS_IN_PROGRESS
    STATUS_ACTIVE = STATUS_IN_PROGRESS

    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PENDING_PAYMENT, 'Pending payment'),
        (STATUS_PAID, 'Paid'),
        (STATUS_IN_PROGRESS, 'In progress'),
        (STATUS_RETURNED, 'Returned'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_DISPUTED, 'Disputed'),
    ]

    # Публичный словарь статусов, который ожидает фронтенд:
    # pending, confirmed, active, returned, completed, disputed (+ cancelled).
    PUBLIC_STATUS_MAP = {
        STATUS_DRAFT: 'pending',
        STATUS_PENDING_PAYMENT: 'pending',
        STATUS_PAID: 'confirmed',
        STATUS_IN_PROGRESS: 'active',
        STATUS_RETURNED: 'returned',
        STATUS_COMPLETED: 'completed',
        STATUS_CANCELLED: 'cancelled',
        STATUS_DISPUTED: 'disputed',
    }
    # Обратный маппинг для входящих PATCH /deals/:id/status/ с публичным именем статуса.
    # Несколько внутренних статусов могут схлопываться в один публичный (pending) —
    # для входящих запросов берём наиболее вероятный целевой внутренний статус.
    PUBLIC_STATUS_INPUT_MAP = {
        'pending': STATUS_PENDING_PAYMENT,
        'confirmed': STATUS_PAID,
        'active': STATUS_IN_PROGRESS,
        'returned': STATUS_RETURNED,
        'completed': STATUS_COMPLETED,
        'cancelled': STATUS_CANCELLED,
        'disputed': STATUS_DISPUTED,
    }

    ESCROW_PENDING = 'pending'
    ESCROW_HELD = 'held'
    ESCROW_RELEASED = 'released'
    ESCROW_REFUNDED = 'refunded'
    ESCROW_FROZEN = 'frozen'

    ESCROW_CHOICES = [
        (ESCROW_PENDING, 'Pending'),
        (ESCROW_HELD, 'Held'),
        (ESCROW_RELEASED, 'Released'),
        (ESCROW_REFUNDED, 'Refunded'),
        (ESCROW_FROZEN, 'Frozen'),
    ]

    # Progress label per status for each role (used by mobile)
    PROGRESS_RENTER = {
        STATUS_DRAFT: 'Черновик сделки',
        STATUS_PENDING_PAYMENT: 'Ожидание оплаты',
        STATUS_PAID: 'Оплата прошла',
        STATUS_IN_PROGRESS: 'Аренда началась',
        STATUS_RETURNED: 'Возврат подтверждён',
        STATUS_COMPLETED: 'Аренда завершена',
        STATUS_CANCELLED: 'Заказ отменён',
        STATUS_DISPUTED: 'Открыт спор',
    }

    PROGRESS_OWNER = {
        STATUS_DRAFT: 'Черновик сделки',
        STATUS_PENDING_PAYMENT: 'Ожидание оплаты',
        STATUS_PAID: 'Оплата прошла',
        STATUS_IN_PROGRESS: 'Аренда активна',
        STATUS_RETURNED: 'Возврат подтверждён',
        STATUS_COMPLETED: 'Аренда завершена, средства зачислены',
        STATUS_CANCELLED: 'Заказ отменён',
        STATUS_DISPUTED: 'Открыт спор',
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
    commission_amount = models.DecimalField('Комиссия платформы', max_digits=12, decimal_places=0)
    total_price = models.DecimalField('Итого', max_digits=12, decimal_places=0)

    status = models.CharField('Статус', max_length=30, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    escrow_status = models.CharField(max_length=20, choices=ESCROW_CHOICES, default=ESCROW_PENDING)
    escrow_amount = models.DecimalField(max_digits=14, decimal_places=0, default=0)
    renter_comment = models.TextField('Комментарий арендатора', blank=True)
    dispute_reason = models.TextField(blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    contact_revealed_at = models.DateTimeField(null=True, blank=True)
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

    @property
    def owner(self):
        return self.item.owner

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

    @property
    def public_status(self) -> str:
        """Статус в словаре, который ожидает фронтенд (см. PUBLIC_STATUS_MAP)."""
        return self.PUBLIC_STATUS_MAP.get(self.status, self.status)


class BookingPhoto(models.Model):
    KIND_BEFORE = 'before'
    KIND_AFTER = 'after'
    KIND_ISSUE = 'issue'

    KIND_CHOICES = [
        (KIND_BEFORE, 'Before'),
        (KIND_AFTER, 'After'),
        (KIND_ISSUE, 'Issue'),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='photos')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='booking_photos')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    image = models.ImageField(upload_to='deal_evidence/')
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'Booking photo #{self.pk} ({self.kind})'


class DealReview(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='reviews')
    listing = models.ForeignKey('catalog.Item', on_delete=models.CASCADE, related_name='reviews')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='written_reviews')
    reviewee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_reviews')
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('booking', 'reviewer')
        ordering = ['-created_at']

    def __str__(self):
        return f'Review #{self.pk}: {self.rating}'

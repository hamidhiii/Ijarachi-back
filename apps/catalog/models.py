from django.db import models
from django.conf import settings
from django.utils.text import slugify
from mptt.models import MPTTModel, TreeForeignKey


class Category(MPTTModel):
    name = models.CharField('Название', max_length=100)
    slug = models.SlugField('Slug', unique=True, max_length=120)
    icon = models.CharField('Иконка', max_length=100, blank=True, help_text='Имя иконки или emoji')
    parent = TreeForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='children',
        verbose_name='Родительская категория',
    )
    is_active = models.BooleanField('Активна', default=True)

    class MPTTMeta:
        order_insertion_by = ['name']

    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)


class Item(models.Model):
    STATUS_APPROVED = 'approved'
    STATUS_PENDING = 'pending'
    STATUS_REJECTED = 'rejected'
    STATUS_INACTIVE = 'inactive'
    STATUS_ACTIVE = STATUS_APPROVED
    STATUS_MODERATION = STATUS_PENDING

    STATUS_CHOICES = [
        (STATUS_APPROVED, 'Одобрено'),
        (STATUS_PENDING, 'На модерации'),
        (STATUS_REJECTED, 'Отклонено'),
        (STATUS_INACTIVE, 'Неактивно'),
    ]

    CONDITION_NEW = 'new'
    CONDITION_EXCELLENT = 'excellent'
    CONDITION_GOOD = 'good'
    CONDITION_FAIR = 'fair'

    CONDITION_CHOICES = [
        (CONDITION_NEW, 'Новое'),
        (CONDITION_EXCELLENT, 'Отличное'),
        (CONDITION_GOOD, 'Хорошее'),
        (CONDITION_FAIR, 'Удовлетворительное'),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Владелец',
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        related_name='items',
        verbose_name='Категория',
    )
    title = models.CharField('Заголовок', max_length=200)
    description = models.TextField('Описание')
    price_per_day = models.DecimalField('Цена за сутки (сум)', max_digits=12, decimal_places=0)
    deposit = models.DecimalField('Залог (сум)', max_digits=12, decimal_places=0, default=0)
    condition = models.CharField('Состояние', max_length=20, choices=CONDITION_CHOICES, default=CONDITION_GOOD)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    rejection_reason = models.TextField('Причина отклонения', blank=True)
    view_count = models.PositiveIntegerField(default=0)
    favorite_count = models.PositiveIntegerField(default=0)
    min_rental_days = models.PositiveIntegerField(default=1)

    # Location
    address = models.CharField('Адрес', max_length=300)
    city = models.CharField('Город', max_length=100, default='Ташкент')
    latitude = models.FloatField('Широта', null=True, blank=True)
    longitude = models.FloatField('Долгота', null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Объявление'
        verbose_name_plural = 'Объявления'
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    @property
    def primary_image(self):
        return self.images.filter(is_primary=True).first() or self.images.first()


class ItemImage(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='images', verbose_name='Вещь')
    image = models.ImageField('Изображение', upload_to='items/')
    is_primary = models.BooleanField('Главное фото', default=False)
    order = models.PositiveSmallIntegerField('Порядок', default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Фото объявления'
        verbose_name_plural = 'Фото объявлений'
        ordering = ['order', 'uploaded_at']

    def __str__(self):
        return f'Фото {self.item.title} (#{self.pk})'

    def save(self, *args, **kwargs):
        # Auto-set as primary if first image
        if not self.pk and not self.item.images.exists():
            self.is_primary = True
        super().save(*args, **kwargs)


class ItemAvailability(models.Model):
    """Stores blocked dates for an item (as a list of ISO date strings)."""
    item = models.OneToOneField(Item, on_delete=models.CASCADE, related_name='availability')
    blocked_dates = models.JSONField('Заблокированные даты', default=list)

    class Meta:
        verbose_name = 'Доступность'
        verbose_name_plural = 'Доступность'

    def __str__(self):
        return f'Доступность: {self.item.title}'

    def is_available(self, start_date, end_date) -> bool:
        """Check if item is available for the given date range."""
        from datetime import date, timedelta
        blocked = set(self.blocked_dates)
        current = start_date
        while current <= end_date:
            if current.isoformat() in blocked:
                return False
            current += timedelta(days=1)
        return True

    def block_range(self, start_date, end_date):
        """Add dates from range to blocked list."""
        from datetime import timedelta
        blocked = set(self.blocked_dates)
        current = start_date
        while current <= end_date:
            blocked.add(current.isoformat())
            current += timedelta(days=1)
        self.blocked_dates = sorted(blocked)
        self.save(update_fields=['blocked_dates'])

    def unblock_range(self, start_date, end_date):
        """Remove dates from blocked list."""
        from datetime import timedelta
        blocked = set(self.blocked_dates)
        current = start_date
        while current <= end_date:
            blocked.discard(current.isoformat())
            current += timedelta(days=1)
        self.blocked_dates = sorted(blocked)
        self.save(update_fields=['blocked_dates'])

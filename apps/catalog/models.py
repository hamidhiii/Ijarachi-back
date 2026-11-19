from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify
from mptt.models import MPTTModel, TreeForeignKey


class Category(MPTTModel):
    name = models.CharField('Название', max_length=100)
    # Узбекское название. Пустое значение означает «ещё не переведено» —
    # клиент в этом случае показывает name.
    name_uz = models.CharField('Название (uz)', max_length=100, blank=True)
    slug = models.SlugField('Slug', unique=True, max_length=120)
    icon = models.CharField('Иконка', max_length=100, blank=True, help_text='Имя иконки или emoji')
    # Определения полей формы размещения для этой категории:
    # [{"key": "size", "label": "Размер", "type": "text|number|select|chips", "options": [...], "unit": "..."}]
    # options обязателен для select/chips, unit опционален. Читает фронт, чтобы строить форму динамически.
    attributes = models.JSONField('Характеристики категории', default=list, blank=True)
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
    # Скрыто модератором (жалоба, нарушение): владелец сам вернуть не может.
    STATUS_BLOCKED = 'blocked'
    # Товар проката только в кабинете owner.rentoo.uz: участвует в остатках и
    # бронях, на rentoo.uz не виден и в лимит объявлений не входит. Кнопка
    # «Опубликовать на Rentoo» переводит его в «На модерации».
    STATUS_CRM = 'crm'
    STATUS_ACTIVE = STATUS_APPROVED
    STATUS_MODERATION = STATUS_PENDING

    STATUS_CHOICES = [
        (STATUS_APPROVED, 'Одобрено'),
        (STATUS_PENDING, 'На модерации'),
        (STATUS_REJECTED, 'Отклонено'),
        (STATUS_INACTIVE, 'Неактивно'),
        (STATUS_BLOCKED, 'Скрыто модератором'),
        (STATUS_CRM, 'Только в кабинете'),
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
    # Объявление описывает модель вещи, а не один экземпляр: у проката может
    # быть 40 одинаковых стульев. Свободный остаток на дату — quantity минус
    # забронированное (apps.crm).
    quantity = models.PositiveIntegerField('Количество', default=1, validators=[MinValueValidator(1)])
    # Снято при окончании тарифа (сверх лимита FREE): статус, в который вернуть
    # объявление, когда тариф снова оплачен. Пусто — не снималось по тарифу.
    plan_paused_status = models.CharField('Снято по тарифу (вернуть в статус)', max_length=20, blank=True)
    # Платное продвижение (apps.billing): действует, пока дата в будущем.
    # Порядок выдачи — apps.catalog.ranking.
    # Точка проката (тариф PRO, apps.crm.Branch); пусто — без привязки.
    branch = models.ForeignKey(
        'crm.Branch', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='items', verbose_name='Точка',
    )
    top_until = models.DateTimeField('В топе до', null=True, blank=True, db_index=True)
    vip_until = models.DateTimeField('VIP до', null=True, blank=True, db_index=True)
    # «Торг»: владелец готов обсуждать цену. Показывается рядом с ценой в
    # каталоге и на карточке — это заявление о числе, а не статус модерации.
    # Умолчание False: объявление, размещённое до появления поля, не должно
    # задним числом начать обещать торг.
    is_negotiable = models.BooleanField('Торг уместен', default=False)
    # Значения характеристик, специфичных для категории (см. Category.attributes),
    # напр. {"size": ["42","44"], "height": 170}. Только скаляры (str/number) и
    # списки строк — не вложенные объекты. PATCH заменяет объект целиком.
    attributes = models.JSONField('Характеристики', default=dict, blank=True)

    # Location
    address = models.CharField('Адрес', max_length=300)
    city = models.CharField('Город', max_length=100, default='Ташкент')
    # Свободная строка, как и city — районов может быть разное число в разных
    # городах, отдельного справочника пока нет.
    district = models.CharField('Район', max_length=100, blank=True)
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
    """
    Дни, которые владелец закрыл вручную (ISO-строки). Брони сюда больше не
    пишутся: их даты считаются по самим броням, см. apps.bookings.availability.
    """
    item = models.OneToOneField(Item, on_delete=models.CASCADE, related_name='availability')
    blocked_dates = models.JSONField('Закрыто владельцем', default=list)

    class Meta:
        verbose_name = 'Доступность'
        verbose_name_plural = 'Доступность'

    def __str__(self):
        return f'Доступность: {self.item.title}'


class Favorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='favorites')
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='favorites')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'item')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user_id} -> {self.item_id}'


class Offer(models.Model):
    """
    A price negotiation thread for one (item, renter) pair.

    One row per proposal rather than one mutable row per pair: `respond`
    always writes a new row, so the back-and-forth stays a readable history
    instead of a single value overwritten in place. Which row is "current"
    is just the latest one for that pair — see `Item.current_offer_for` on
    the queryset side (views.py), not modelled here.
    """
    STATUS_PENDING = 'pending'
    STATUS_ACCEPTED = 'accepted'
    STATUS_REJECTED = 'rejected'
    STATUS_WITHDRAWN = 'withdrawn'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Ожидает ответа'),
        (STATUS_ACCEPTED, 'Принято'),
        (STATUS_REJECTED, 'Отклонено'),
        (STATUS_WITHDRAWN, 'Снято предложением'),
    ]

    PROPOSER_RENTER = 'renter'
    PROPOSER_OWNER = 'owner'
    PROPOSER_CHOICES = [
        (PROPOSER_RENTER, 'Арендатор'),
        (PROPOSER_OWNER, 'Владелец'),
    ]

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='offers', verbose_name='Объявление')
    # Denormalised onto every row (not just derivable via item.owner) because
    # the owner side of a thread is looked up by "offers I received" — a
    # query that would otherwise join through Item on every request.
    renter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='price_offers', verbose_name='Арендатор',
    )
    amount = models.DecimalField('Предложенная цена за сутки (сум)', max_digits=12, decimal_places=0)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    # Whoever proposed `amount` — the other side is who gets to respond.
    proposed_by = models.CharField('Кто предложил', max_length=10, choices=PROPOSER_CHOICES, default=PROPOSER_RENTER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Предложение цены'
        verbose_name_plural = 'Предложения цены'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['item', 'renter', '-created_at']),
        ]

    def __str__(self):
        return f'{self.item_id} · {self.renter_id} · {self.amount} ({self.status})'

    @classmethod
    def accepted_for(cls, item, renter):
        """
        Согласованная цена пары (объявление, арендатор): последняя строка ветки,
        если она принята. Новое предложение после принятия открывает торг заново,
        и до ответа действует цена из объявления.
        """
        latest = cls.objects.filter(item=item, renter=renter).order_by('-created_at', '-pk').first()
        return latest if latest is not None and latest.status == cls.STATUS_ACCEPTED else None


class PhoneReveal(models.Model):
    """
    Нажатие «Показать номер» (решение 16.11.2026): каждое нажатие — строка.
    В статистику идут только `counted`: первое нажатие пользователя по
    объявлению за 24 часа; нажатия владельца по своему объявлению не считаются.
    """
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='phone_reveals', verbose_name='Объявление')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='phone_reveals', verbose_name='Пользователь',
    )
    counted = models.BooleanField('Учитывается в статистике', default=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Показ номера'
        verbose_name_plural = 'Показы номера'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['item', 'user', '-created_at'])]

    def __str__(self):
        return f'{self.user_id} → {self.item_id} {self.created_at:%d.%m.%Y %H:%M}'


class ListingDailyStat(models.Model):
    """Просмотры карточки по дням — для статистики владельца за месяц."""
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='daily_stats', verbose_name='Объявление')
    date = models.DateField('День')
    views = models.PositiveIntegerField('Просмотры', default=0)

    class Meta:
        verbose_name = 'Статистика объявления за день'
        verbose_name_plural = 'Статистика объявлений по дням'
        constraints = [models.UniqueConstraint(fields=['item', 'date'], name='listing_daily_stat_once')]

    def __str__(self):
        return f'{self.item_id} {self.date}: {self.views}'

    @classmethod
    def bump_views(cls, item_id):
        from django.db import IntegrityError, transaction
        from django.db.models import F
        from django.utils import timezone

        today = timezone.localdate()
        if cls.objects.filter(item_id=item_id, date=today).update(views=F('views') + 1):
            return
        try:
            with transaction.atomic():
                cls.objects.create(item_id=item_id, date=today, views=1)
        except IntegrityError:
            # Параллельный просмотр создал строку первым.
            cls.objects.filter(item_id=item_id, date=today).update(views=F('views') + 1)


class Report(models.Model):
    """Жалоба на объявление (решение 16.11.2026). Разбирает сотрудник в очереди модерации."""
    REASON_FRAUD = 'fraud'
    REASON_PROHIBITED = 'prohibited'
    REASON_WRONG_INFO = 'wrong_info'
    REASON_DUPLICATE = 'duplicate'
    REASON_UNAVAILABLE = 'unavailable'
    REASON_OFFENSIVE = 'offensive'
    REASON_OTHER = 'other'
    REASON_CHOICES = [
        (REASON_FRAUD, 'Мошенничество'),
        (REASON_PROHIBITED, 'Запрещённая вещь'),
        (REASON_WRONG_INFO, 'Неверные цена, фото или описание'),
        (REASON_DUPLICATE, 'Дубликат'),
        (REASON_UNAVAILABLE, 'Вещь уже не сдаётся'),
        (REASON_OFFENSIVE, 'Оскорбительное содержание'),
        (REASON_OTHER, 'Другое'),
    ]

    STATUS_NEW = 'new'
    STATUS_DISMISSED = 'dismissed'
    STATUS_ACTION_TAKEN = 'action_taken'
    STATUS_CHOICES = [
        (STATUS_NEW, 'Новая'),
        (STATUS_DISMISSED, 'Отклонена'),
        (STATUS_ACTION_TAKEN, 'Объявление скрыто'),
    ]

    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='reports', verbose_name='Объявление')
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='listing_reports', verbose_name='Кто пожаловался',
    )
    reason = models.CharField('Причина', max_length=20, choices=REASON_CHOICES)
    comment = models.TextField('Комментарий', max_length=1000, blank=True)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='Кто разобрал',
    )
    resolution = models.CharField('Решение (комментарий)', max_length=500, blank=True)
    resolved_at = models.DateTimeField('Разобрана', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Жалоба'
        verbose_name_plural = 'Жалобы'
        ordering = ['created_at']
        indexes = [models.Index(fields=['status', 'created_at'])]
        constraints = [
            # Одна открытая жалоба пользователя на объявление — без накрутки.
            models.UniqueConstraint(
                fields=['item', 'reporter'], condition=models.Q(status='new'), name='report_one_open_per_user',
            ),
        ]

    def __str__(self):
        return f'Жалоба #{self.pk} на {self.item_id}: {self.get_reason_display()}'

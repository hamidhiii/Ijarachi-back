"""
Кабинет владельца (owner.rentoo.uz, решение 16.11.2026): брони, клиенты,
остатки, сотрудники и филиалы проката. Всё принадлежит аккаунту владельца
(`owner`); сотрудник работает от его имени, см. apps.crm.access.
"""
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


class Branch(models.Model):
    """Точка (филиал) проката — тариф PRO. Объявление привязывается к точке."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='branches', verbose_name='Владелец')
    name = models.CharField('Название', max_length=100)
    address = models.CharField('Адрес', max_length=300, blank=True)
    phone = models.CharField('Телефон точки', max_length=20, blank=True)
    is_active = models.BooleanField('Работает', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Точка (филиал)'
        verbose_name_plural = 'Точки (филиалы)'
        ordering = ['name']

    def __str__(self):
        return self.name


class StaffMember(models.Model):
    """
    Сотрудник проката с доступом к кабинету владельца — тариф BUSINESS и выше.
    manager — всё, кроме сотрудников и тарифа; viewer — только смотрит.
    """
    ROLE_MANAGER = 'manager'
    ROLE_VIEWER = 'viewer'
    ROLE_CHOICES = [
        (ROLE_MANAGER, 'Менеджер'),
        (ROLE_VIEWER, 'Только просмотр'),
    ]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='staff_members', verbose_name='Владелец')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='staff_of', verbose_name='Сотрудник')
    role = models.CharField('Роль', max_length=20, choices=ROLE_CHOICES, default=ROLE_MANAGER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Сотрудник'
        verbose_name_plural = 'Сотрудники'
        ordering = ['created_at']
        constraints = [models.UniqueConstraint(fields=['owner', 'user'], name='crm_staff_once_per_owner')]

    def __str__(self):
        return f'{self.user} у {self.owner} ({self.get_role_display()})'


class Client(models.Model):
    """Клиент проката: контакты и заметки; история — его брони (Reservation)."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='crm_clients', verbose_name='Владелец')
    name = models.CharField('Имя', max_length=200)
    phone = models.CharField('Телефон', max_length=20, blank=True)
    # Если клиент — пользователь Rentoo с этим номером, ссылка проставляется сама.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='Аккаунт Rentoo',
    )
    notes = models.TextField('Заметки', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Клиент'
        verbose_name_plural = 'Клиенты'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'phone'], condition=~Q(phone=''), name='crm_client_phone_once_per_owner',
            ),
        ]

    def __str__(self):
        return f'{self.name} {self.phone}'.strip()


class Reservation(models.Model):
    """
    Бронь в календаре владельца — пришла через Rentoo, Instagram, по телефону или
    иначе. Занимает `quantity` единиц объявления на каждый день с start_date по
    end_date включительно, пока она `booked` или `issued` (см.
    apps.bookings.availability — те же правила, что у сделок).
    """
    SOURCE_RENTOO = 'rentoo'
    SOURCE_INSTAGRAM = 'instagram'
    SOURCE_PHONE = 'phone'
    SOURCE_OTHER = 'other'
    SOURCE_CHOICES = [
        (SOURCE_RENTOO, 'Rentoo'),
        (SOURCE_INSTAGRAM, 'Instagram'),
        (SOURCE_PHONE, 'Телефон'),
        (SOURCE_OTHER, 'Другое'),
    ]

    STATUS_BOOKED = 'booked'
    STATUS_ISSUED = 'issued'
    STATUS_RETURNED = 'returned'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_BOOKED, 'Забронировано'),
        (STATUS_ISSUED, 'Выдано'),
        (STATUS_RETURNED, 'Возвращено'),
        (STATUS_CANCELLED, 'Отменено'),
    ]
    OCCUPYING_STATUSES = (STATUS_BOOKED, STATUS_ISSUED)
    TRANSITIONS = {
        STATUS_BOOKED: {STATUS_ISSUED, STATUS_CANCELLED},
        STATUS_ISSUED: {STATUS_RETURNED, STATUS_CANCELLED},
        STATUS_RETURNED: set(),
        STATUS_CANCELLED: set(),
    }

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='crm_reservations', verbose_name='Владелец')
    item = models.ForeignKey('catalog.Item', on_delete=models.CASCADE, related_name='reservations', verbose_name='Объявление')
    client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reservations', verbose_name='Клиент',
    )
    quantity = models.PositiveIntegerField('Количество', default=1, validators=[MinValueValidator(1)])
    start_date = models.DateField('Выдача')
    end_date = models.DateField('Возврат')
    source = models.CharField('Источник', max_length=20, choices=SOURCE_CHOICES, default=SOURCE_PHONE)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default=STATUS_BOOKED)
    price = models.DecimalField('Сумма (сум)', max_digits=12, decimal_places=0, null=True, blank=True)
    notes = models.TextField('Заметки', blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='Кто внёс',
    )
    # Напоминание о выдаче/возврате отправлено (за какой день) — задача идемпотентна.
    pickup_reminded_on = models.DateField(null=True, blank=True, editable=False)
    return_reminded_on = models.DateField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Бронь (CRM)'
        verbose_name_plural = 'Брони (CRM)'
        ordering = ['start_date', 'pk']
        indexes = [
            models.Index(fields=['item', 'start_date', 'end_date']),
            models.Index(fields=['owner', 'start_date']),
        ]
        constraints = [
            models.CheckConstraint(check=Q(end_date__gte=models.F('start_date')), name='crm_reservation_dates_order'),
        ]

    def __str__(self):
        return f'{self.item_id} × {self.quantity}: {self.start_date}–{self.end_date}'


class CrmBotLink(models.Model):
    """
    Чат CRM-бота, привязанный к пользователю: владелец или менеджер нажал в
    кабинете «Подключить Telegram» и открыл бота по одноразовой ссылке
    (apps.crm.telegram). Туда приходят напоминания с кнопками.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='crm_bot_link', verbose_name='Пользователь',
    )
    chat_id = models.BigIntegerField('Telegram chat_id', unique=True)
    username = models.CharField('Telegram username', max_length=64, blank=True)
    # Язык сообщений: из language_code Telegram, по умолчанию узбекский.
    language = models.CharField('Язык', max_length=2, default='uz')
    linked_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'CRM-бот: привязка'
        verbose_name_plural = 'CRM-бот: привязки'

    def __str__(self):
        return f'{self.user_id} -> chat {self.chat_id}'

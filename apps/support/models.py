"""
Техподдержка: обращение с сайта (rentoo.uz) или кабинета (owner.rentoo.uz) —
переписка, которую поддержка ведёт прямо из Telegram (apps.support.telegram).
"""
import secrets

from django.conf import settings
from django.db import models


def _key():
    return secrets.token_urlsafe(24)


class SupportTicket(models.Model):
    SOURCE_WEB = 'web'
    SOURCE_OWNER = 'owner'
    SOURCE_CHOICES = [(SOURCE_WEB, 'rentoo.uz'), (SOURCE_OWNER, 'Кабинет')]

    STATUS_OPEN = 'open'
    STATUS_ANSWERED = 'answered'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = [(STATUS_OPEN, 'Ждёт ответа'), (STATUS_ANSWERED, 'Отвечено'), (STATUS_CLOSED, 'Закрыто')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name='support_tickets', verbose_name='Пользователь')
    name = models.CharField('Имя', max_length=120, blank=True)
    phone = models.CharField('Телефон для связи', max_length=32, blank=True)
    source = models.CharField('Откуда', max_length=10, choices=SOURCE_CHOICES, default=SOURCE_WEB)
    status = models.CharField('Статус', max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)
    # Гость видит свою переписку по этому ключу (хранится в его браузере).
    access_key = models.CharField(max_length=64, default=_key, unique=True, editable=False)
    page = models.CharField('Страница', max_length=300, blank=True)
    reminded_at = models.DateTimeField('Последнее напоминание сотрудникам', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Обращение'
        verbose_name_plural = 'Обращения'

    def __str__(self):
        return f'#{self.pk} {self.who()}'

    def who(self):
        if self.user_id:
            profile = getattr(self.user, 'profile', None)
            name = getattr(profile, 'full_name', '') or self.name
            return f'{name} {self.user.phone}'.strip()
        return f'{self.name} {self.phone}'.strip() or 'Гость'


class SupportMessage(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='messages')
    text = models.TextField('Текст', max_length=4000)
    from_staff = models.BooleanField('От поддержки', default=False)
    staff_name = models.CharField('Кто ответил', max_length=120, blank=True)
    read_by_user = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Сообщение'
        verbose_name_plural = 'Сообщения'


class SupportTelegramMessage(models.Model):
    """Сообщение бота у сотрудника: реплай на него — ответ в это обращение."""
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='telegram_messages')
    chat_id = models.BigIntegerField()
    message_id = models.BigIntegerField()

    class Meta:
        unique_together = [('chat_id', 'message_id')]

from django.conf import settings
from django.db import models


class Notification(models.Model):
    TYPE_DEAL = 'deal'
    TYPE_PAYMENT = 'payment'
    TYPE_CHAT = 'chat'
    TYPE_SYSTEM = 'system'

    TYPE_CHOICES = [
        (TYPE_DEAL, 'Deal'),
        (TYPE_PAYMENT, 'Payment'),
        (TYPE_CHAT, 'Chat'),
        (TYPE_SYSTEM, 'System'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    payload = models.JSONField(default=dict)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user_id}:{self.type}:{self.pk}'


class PushSubscription(models.Model):
    """
    Подписка браузера на Web Push (уведомление доходит, даже когда вкладка
    закрыта — доставляет сервер, не клиент). Один пользователь может иметь
    несколько подписок (разные устройства/браузеры).
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='push_subscriptions')
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user_id}: {self.endpoint[:60]}'

    def as_webpush_subscription_info(self) -> dict:
        return {
            'endpoint': self.endpoint,
            'keys': {'p256dh': self.p256dh, 'auth': self.auth},
        }


class NotificationTemplate(models.Model):
    key = models.CharField(max_length=100)
    language = models.CharField(max_length=5, default='ru')
    title = models.CharField(max_length=200)
    body = models.TextField()
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('key', 'language')
        ordering = ['key', 'language']

    def __str__(self):
        return f'{self.key}:{self.language}'


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=120)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.action} #{self.pk}'

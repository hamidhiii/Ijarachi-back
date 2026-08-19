from django.urls import path

from apps.users.views.telegram import TelegramWebhookView

urlpatterns = [
    path('webhook/<str:secret>/', TelegramWebhookView.as_view(), name='telegram-webhook'),
]

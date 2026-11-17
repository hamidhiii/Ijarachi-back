from django.urls import path

from apps.crm.bot_views import CrmBotWebhookView
from apps.users.views.telegram import TelegramAppBotWebhookView, TelegramWebhookView

urlpatterns = [
    # Before `webhook/<secret>/`, which would otherwise take «app» for a secret.
    # Under /webhook/ so nginx's auth_basic exception for Telegram covers it.
    path('webhook/app/', TelegramAppBotWebhookView.as_view(), name='telegram-app-webhook'),
    # Раньше `webhook/<secret>/`, иначе `crm` приняли бы за секрет OTP-бота.
    path('webhook/crm/', CrmBotWebhookView.as_view(), name='telegram-crm-webhook'),
    path('webhook/<str:secret>/', TelegramWebhookView.as_view(), name='telegram-webhook'),
]

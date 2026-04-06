from django.urls import path
from .views import PaymeWebhookView, ClickWebhookView

urlpatterns = [
    path('payme/webhook/', PaymeWebhookView.as_view(), name='payme-webhook'),
    path('click/webhook/', ClickWebhookView.as_view(), name='click-webhook'),
]

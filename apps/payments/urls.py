from django.urls import path
from .views import PaymeWebhookView, ClickWebhookView

urlpatterns = [
    path('payme/callback/', PaymeWebhookView.as_view(), name='payme-callback'),
    path('click/callback/', ClickWebhookView.as_view(), name='click-callback'),
    path('payme/webhook/', PaymeWebhookView.as_view(), name='payme-webhook'),
    path('click/webhook/', ClickWebhookView.as_view(), name='click-webhook'),
]

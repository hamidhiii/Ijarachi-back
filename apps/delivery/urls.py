from django.urls import path

from .views import DeliveryCalculateView, DeliveryWebhookView

urlpatterns = [
    path('delivery/calculate/', DeliveryCalculateView.as_view(), name='delivery-calculate'),
    path('delivery/webhook/', DeliveryWebhookView.as_view(), name='delivery-webhook'),
]

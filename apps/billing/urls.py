from django.urls import path

from .views import (
    ClickWebhookView,
    OrderDetailView,
    OrderListCreateView,
    PaymeWebhookView,
    PlanListView,
    SubscriptionView,
)

urlpatterns = [
    path('plans/', PlanListView.as_view(), name='billing-plans'),
    path('subscription/', SubscriptionView.as_view(), name='billing-subscription'),
    path('orders/', OrderListCreateView.as_view(), name='billing-orders'),
    path('orders/<int:pk>/', OrderDetailView.as_view(), name='billing-order-detail'),
    path('payme/', PaymeWebhookView.as_view(), name='billing-payme'),
    path('click/prepare/', ClickWebhookView.as_view(), name='billing-click-prepare'),
    path('click/complete/', ClickWebhookView.as_view(), name='billing-click-complete'),
]

from django.urls import path

from .admin_api import AdminExtendView, AdminMetricsView, AdminOrderListView, AdminSubscriptionListView

urlpatterns = [
    path('subscriptions/', AdminSubscriptionListView.as_view(), name='admin-billing-subscriptions'),
    path('subscriptions/extend/', AdminExtendView.as_view(), name='admin-billing-extend'),
    path('orders/', AdminOrderListView.as_view(), name='admin-billing-orders'),
    path('metrics/', AdminMetricsView.as_view(), name='admin-billing-metrics'),
]

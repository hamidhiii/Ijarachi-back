from django.urls import path

from .views import (
    NotificationListView, NotificationReadAllView, NotificationReadView, PushSubscribeView, VapidKeyView,
)

urlpatterns = [
    path('notifications/', NotificationListView.as_view(), name='notifications-list'),
    path('notifications/read-all/', NotificationReadAllView.as_view(), name='notifications-read-all'),
    path('notifications/<int:pk>/read/', NotificationReadView.as_view(), name='notifications-read'),
    path('push/subscribe/', PushSubscribeView.as_view(), name='push-subscribe'),
    path('push/vapid-key/', VapidKeyView.as_view(), name='push-vapid-key'),
]

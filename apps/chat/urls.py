from django.urls import path
from .views import ChatHistoryView

urlpatterns = [
    path('chat/<int:booking_id>/', ChatHistoryView.as_view(), name='chat-history'),
]

from django.urls import path

from .views import ConversationListCreateView, MessageListView

urlpatterns = [
    path('chat/conversations/', ConversationListCreateView.as_view(), name='chat-conversations'),
    path('chat/conversations/<int:pk>/messages/', MessageListView.as_view(), name='chat-messages'),
]

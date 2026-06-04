from django.urls import path

from .views import ConversationListCreateView, ConversationReadView, MessageListView

urlpatterns = [
    path('chat/conversations/', ConversationListCreateView.as_view(), name='chat-conversations'),
    path('chat/conversations/<int:pk>/messages/', MessageListView.as_view(), name='chat-messages'),
    path('chat/conversations/<int:pk>/read/', ConversationReadView.as_view(), name='chat-conversation-read'),
]

from django.db import models
from rest_framework import generics, permissions
from django.utils.translation import gettext_lazy as _
from .models import ChatMessage
from .serializers import ChatMessageSerializer

class ChatHistoryView(generics.ListAPIView):
    """
    Message history for a specific booking.
    """
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        booking_id = self.kwargs['booking_id']
        user = self.request.user
        
        # Security: Return messages only if user is party to the booking/message
        return ChatMessage.objects.filter(
            booking_id=booking_id
        ).filter(
            models.Q(sender=user) | models.Q(recipient=user)
        ).select_related('sender', 'recipient').order_by('created_at')

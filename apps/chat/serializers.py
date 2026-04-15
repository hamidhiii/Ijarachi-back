from rest_framework import serializers
from .models import ChatMessage

class ChatMessageSerializer(serializers.ModelSerializer):
    sender_phone = serializers.CharField(source='sender.phone', read_only=True)
    
    class Meta:
        model = ChatMessage
        fields = ['id', 'booking', 'sender', 'sender_phone', 'recipient', 'text', 'created_at', 'is_read']
        read_only_fields = ['id', 'sender', 'sender_phone', 'created_at', 'is_read']

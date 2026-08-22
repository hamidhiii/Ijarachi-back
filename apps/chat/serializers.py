from rest_framework import serializers

from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    sender = serializers.SerializerMethodField()
    sender_phone = serializers.CharField(source='sender.phone', read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'conversation', 'sender', 'sender_phone', 'text', 'image', 'is_read', 'created_at']
        read_only_fields = ['conversation', 'sender', 'sender_phone', 'is_read', 'created_at']

    def get_sender(self, obj):
        try:
            full_name = obj.sender.profile.full_name or obj.sender.phone
        except Exception:
            full_name = obj.sender.phone
        return {'id': obj.sender_id, 'full_name': full_name}


class ConversationSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField()
    participant_phones = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ['id', 'listing', 'deal', 'participant_phones', 'last_message', 'created_at', 'updated_at']
        read_only_fields = fields

    def get_last_message(self, obj):
        message = obj.messages.order_by('-created_at').first()
        if not message:
            return None
        return MessageSerializer(message, context=self.context).data

    def get_participant_phones(self, obj):
        return list(obj.participants.values_list('phone', flat=True))


class ConversationCreateSerializer(serializers.Serializer):
    deal_id = serializers.IntegerField()

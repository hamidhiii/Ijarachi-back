from rest_framework import serializers

from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    sender_phone = serializers.CharField(source='sender.phone', read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'conversation', 'sender', 'sender_phone', 'text', 'image', 'is_read', 'created_at']
        read_only_fields = ['conversation', 'sender', 'sender_phone', 'is_read', 'created_at']


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
    listing_id = serializers.IntegerField(required=False)
    deal_id = serializers.IntegerField(required=False)
    user_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        if not any(attrs.get(key) for key in ['listing_id', 'deal_id', 'user_id']):
            raise serializers.ValidationError('Укажите listing_id, deal_id или user_id.')
        return attrs

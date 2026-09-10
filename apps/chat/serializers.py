from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Conversation, Message
from core.schema import UserMiniSerializer
from apps.bookings.serializers import ListingMiniSerializer, _serialize_listing_mini


class MessageSerializer(serializers.ModelSerializer):
    sender = serializers.SerializerMethodField()
    sender_phone = serializers.CharField(source='sender.phone', read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'conversation', 'sender', 'sender_phone', 'text', 'image', 'is_read', 'created_at']
        read_only_fields = ['conversation', 'sender', 'sender_phone', 'is_read', 'created_at']

    @extend_schema_field(UserMiniSerializer)
    def get_sender(self, obj):
        try:
            full_name = obj.sender.profile.full_name
        except Exception:
            full_name = ''
        return {'id': obj.sender_id, 'full_name': full_name}


class ConversationSerializer(serializers.ModelSerializer):
    listing = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    participant_phones = serializers.SerializerMethodField()
    interlocutor = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'listing', 'deal', 'interlocutor', 'unread_count',
            'participant_phones', 'last_message', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    @extend_schema_field(ListingMiniSerializer(allow_null=True))
    def get_listing(self, obj):
        """
        Вещь диалога как объект {id, title, image} — не голый id, чтобы строка
        диалога могла показать название/фото без похода за самой сделкой.
        """
        if obj.listing_id is None:
            return None
        return _serialize_listing_mini(obj.listing, self.context.get('request'))

    @extend_schema_field(MessageSerializer(allow_null=True))
    def get_last_message(self, obj):
        message = obj.messages.order_by('-created_at').first()
        if not message:
            return None
        return MessageSerializer(message, context=self.context).data

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_participant_phones(self, obj):
        return list(obj.participants.values_list('phone', flat=True))

    @extend_schema_field(UserMiniSerializer(allow_null=True))
    def get_interlocutor(self, obj):
        """Второй участник диалога; null, если запрос без пользователя."""
        user = getattr(self.context.get('request'), 'user', None)
        if user is None or not user.is_authenticated:
            return None
        other = next((p for p in obj.participants.all() if p.pk != user.pk), None)
        if other is None:
            return None
        try:
            full_name = other.profile.full_name
        except Exception:
            full_name = ''
        return {'id': other.pk, 'full_name': full_name}

    @extend_schema_field(serializers.IntegerField())
    def get_unread_count(self, obj):
        """Непрочитанные входящие: свои сообщения не считаются."""
        user = getattr(self.context.get('request'), 'user', None)
        if user is None or not user.is_authenticated:
            return 0
        # Считаем по prefetch_related('messages') из вьюхи, без запроса на строку.
        return sum(1 for m in obj.messages.all() if not m.is_read and m.sender_id != user.pk)


class ConversationCreateSerializer(serializers.Serializer):
    """
    {"deal_id": ...} — открыть/получить диалог по оплаченной сделке (старый флоу).
    {"listing_id": ...} — открыть/получить диалог-обращение по объявлению до брони.
    Ровно одно из двух полей.
    """
    deal_id = serializers.IntegerField(required=False)
    listing_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        if bool(attrs.get('deal_id')) == bool(attrs.get('listing_id')):
            raise serializers.ValidationError('Укажите ровно одно из полей: deal_id или listing_id.')
        return attrs


class ConversationReadResponseSerializer(serializers.Serializer):
    """Ответ POST /chat/conversations/{id}/read/."""
    detail = serializers.CharField()
    updated = serializers.IntegerField(help_text='Сколько сообщений помечено прочитанными.')

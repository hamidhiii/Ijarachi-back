from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Notification, NotificationTemplate, PushSubscription

# Заголовки/описания по умолчанию, если для типа нет активного NotificationTemplate.
DEFAULT_TITLES = {
    Notification.TYPE_DEAL: 'Обновление по сделке',
    Notification.TYPE_PAYMENT: 'Обновление по оплате',
    Notification.TYPE_CHAT: 'Новое сообщение',
    Notification.TYPE_SYSTEM: 'Системное уведомление',
}


class NotificationSerializer(serializers.ModelSerializer):
    """
    В БД хранятся только `type` + произвольный `payload`; для API собираем
    человекочитаемые title/description (из NotificationTemplate, если задан,
    иначе — из payload/дефолтов), а также единственный поддерживаемый канал
    `in_app` и ссылку на связанный объект.
    """
    title = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    channel = serializers.SerializerMethodField()
    unread = serializers.SerializerMethodField()
    link = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ['id', 'title', 'description', 'channel', 'unread', 'created_at', 'link', 'type', 'payload']
        read_only_fields = fields

    def _template(self, obj):
        return NotificationTemplate.objects.filter(key=obj.type, language='ru', is_active=True).first()

    @extend_schema_field(serializers.CharField())
    def get_title(self, obj):
        payload = obj.payload or {}
        if payload.get('title'):
            return payload['title']
        template = self._template(obj)
        if template:
            return template.title
        return DEFAULT_TITLES.get(obj.type, 'Уведомление')

    @extend_schema_field(serializers.CharField(allow_blank=True))
    def get_description(self, obj):
        payload = obj.payload or {}
        if payload.get('message'):
            return payload['message']
        if payload.get('description'):
            return payload['description']
        template = self._template(obj)
        if template:
            try:
                return template.body.format(**payload)
            except Exception:
                return template.body
        return ''

    @extend_schema_field(serializers.ChoiceField(choices=['in_app']))
    def get_channel(self, obj):
        return 'in_app'

    @extend_schema_field(serializers.BooleanField())
    def get_unread(self, obj):
        return not obj.is_read

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_link(self, obj):
        """
        Реальные маршруты фронта (не /deals//listings//chat/ — те не существуют):
        сделка → /booking/<id>, объявление → /product/<id>, сообщение →
        /messages?listing=<id> или /messages?deal=<id>, KYC → /profile.
        payload['link'] (ставится в местах, где известен точный контекст —
        напр. чат, KYC) всегда побеждает эти общие правила по id.
        """
        payload = obj.payload or {}
        if payload.get('link'):
            return payload['link']
        if payload.get('booking_id'):
            return f"/booking/{payload['booking_id']}"
        if payload.get('deal_id'):
            return f"/booking/{payload['deal_id']}"
        if payload.get('listing_id'):
            return f"/product/{payload['listing_id']}"
        return None


class PushSubscriptionKeysSerializer(serializers.Serializer):
    p256dh = serializers.CharField()
    auth = serializers.CharField()


class PushSubscriptionSerializer(serializers.Serializer):
    """
    POST /push/subscribe/ — тело ровно то, что отдаёт браузер из
    PushManager.subscribe(): {endpoint, keys: {p256dh, auth}}.
    """
    endpoint = serializers.URLField(max_length=500)
    keys = PushSubscriptionKeysSerializer()

    def create(self, validated_data):
        user = self.context['request'].user
        keys = validated_data['keys']
        subscription, _ = PushSubscription.objects.update_or_create(
            endpoint=validated_data['endpoint'],
            defaults={'user': user, 'p256dh': keys['p256dh'], 'auth': keys['auth']},
        )
        return subscription


class PushUnsubscribeSerializer(serializers.Serializer):
    endpoint = serializers.URLField(max_length=500)

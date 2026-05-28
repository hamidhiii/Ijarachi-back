from rest_framework import serializers


class DeliveryCalculateSerializer(serializers.Serializer):
    from_lat = serializers.FloatField()
    from_lng = serializers.FloatField()
    to_lat = serializers.FloatField()
    to_lng = serializers.FloatField()


class DeliveryWebhookSerializer(serializers.Serializer):
    deal_id = serializers.IntegerField(required=False)
    yandex_order_id = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField()
    payload = serializers.JSONField(required=False)

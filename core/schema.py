"""Общие куски описания API, которые нужны нескольким приложениям."""
from rest_framework import serializers


class DetailSerializer(serializers.Serializer):
    """Стандартный ответ DRF об ошибке: {"detail": "..."}."""
    detail = serializers.CharField()


class UserMiniSerializer(serializers.Serializer):
    """Краткая карточка пользователя во вложенных ответах."""
    id = serializers.IntegerField()
    full_name = serializers.CharField()


class OwnerMiniSerializer(serializers.Serializer):
    """Владелец объявления: {id, full_name, shop_name, account_type, avatar, rating, verified}."""
    id = serializers.IntegerField()
    full_name = serializers.CharField()
    shop_name = serializers.CharField(required=False)
    account_type = serializers.ChoiceField(choices=['private', 'shop'], required=False)
    avatar = serializers.URLField(allow_null=True, required=False)
    rating = serializers.FloatField()
    verified = serializers.BooleanField()
    myid_verified = serializers.BooleanField(required=False, help_text='Значок «Проверен MyID»')

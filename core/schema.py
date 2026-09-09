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
    """Владелец объявления: {id, full_name, rating, verified}."""
    id = serializers.IntegerField()
    full_name = serializers.CharField()
    rating = serializers.FloatField()
    verified = serializers.BooleanField()

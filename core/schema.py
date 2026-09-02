"""Общие куски описания API, которые нужны нескольким приложениям."""
from rest_framework import serializers


class DetailSerializer(serializers.Serializer):
    """Стандартный ответ DRF об ошибке: {"detail": "..."}."""
    detail = serializers.CharField()


class UserMiniSerializer(serializers.Serializer):
    """Краткая карточка пользователя во вложенных ответах."""
    id = serializers.IntegerField()
    full_name = serializers.CharField()

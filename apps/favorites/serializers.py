from rest_framework import serializers
from .models import FavoriteItem
from apps.catalog.serializers import ItemListSerializer

class FavoriteItemSerializer(serializers.ModelSerializer):
    item = ItemListSerializer(read_only=True)
    item_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = FavoriteItem
        fields = ['id', 'item', 'item_id', 'created_at']

    def validate_item_id(self, value):
        from apps.catalog.models import Item
        if not Item.objects.filter(id=value).exists():
            raise serializers.ValidationError("Item not found.")
        return value

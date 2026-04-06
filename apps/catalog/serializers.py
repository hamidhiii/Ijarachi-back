from rest_framework import serializers
from mptt.templatetags.mptt_tags import cache_tree_children
from .models import Category, Item, ItemImage, ItemAvailability
from apps.users.serializers import ProfileSerializer


class CategorySerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'icon', 'children']

    def get_children(self, obj):
        if obj.get_children().exists():
            return CategorySerializer(obj.get_children().filter(is_active=True), many=True).data
        return []


class CategoryFlatSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'icon', 'parent']


# ─── Item Images ──────────────────────────────────────────────────────────────

class ItemImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemImage
        fields = ['id', 'image', 'is_primary', 'order']
        read_only_fields = ['id']


class ItemImageUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemImage
        fields = ['image', 'is_primary', 'order']


# ─── Item ─────────────────────────────────────────────────────────────────────

class ItemListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for catalog list view."""
    primary_image = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True)
    owner_name = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = [
            'id', 'title', 'price_per_day', 'deposit',
            'condition', 'city', 'address',
            'category_name', 'primary_image',
            'owner_name', 'created_at',
        ]

    def get_primary_image(self, obj):
        img = obj.primary_image
        if img:
            request = self.context.get('request')
            return request.build_absolute_uri(img.image.url) if request else img.image.url
        return None

    def get_owner_name(self, obj):
        try:
            return obj.owner.profile.full_name or obj.owner.phone
        except Exception:
            return obj.owner.phone


class ItemDetailSerializer(serializers.ModelSerializer):
    """Full serializer for single item view."""
    images = ItemImageSerializer(many=True, read_only=True)
    category = CategoryFlatSerializer(read_only=True)
    blocked_dates = serializers.SerializerMethodField()
    owner = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = [
            'id', 'title', 'description', 'price_per_day', 'deposit',
            'condition', 'status', 'city', 'address', 'latitude', 'longitude',
            'category', 'images', 'blocked_dates', 'owner', 'created_at',
        ]

    def get_blocked_dates(self, obj):
        try:
            return obj.availability.blocked_dates
        except ItemAvailability.DoesNotExist:
            return []

    def get_owner(self, obj):
        try:
            profile = obj.owner.profile
            request = self.context.get('request')
            avatar_url = None
            if profile.avatar:
                avatar_url = request.build_absolute_uri(profile.avatar.url) if request else profile.avatar.url
            return {
                'id': obj.owner.id,
                'name': profile.full_name or obj.owner.phone,
                'rating': profile.rating,
                'rating_count': profile.rating_count,
                'avatar': avatar_url,
                'verification_status': profile.verification_status,
            }
        except Exception:
            return {'id': obj.owner.id, 'name': obj.owner.phone}


class ItemCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Item
        fields = [
            'title', 'description', 'category',
            'price_per_day', 'deposit', 'condition',
            'address', 'city', 'latitude', 'longitude',
        ]

    def validate_price_per_day(self, value):
        if value <= 0:
            raise serializers.ValidationError('Цена должна быть больше нуля.')
        return value

    def validate_deposit(self, value):
        if value < 0:
            raise serializers.ValidationError('Залог не может быть отрицательным.')
        return value

    def create(self, validated_data):
        user = self.context['request'].user
        item = Item.objects.create(owner=user, status=Item.STATUS_MODERATION, **validated_data)
        # Create empty availability record
        ItemAvailability.objects.create(item=item)
        return item


class ItemUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Item
        fields = [
            'title', 'description', 'category',
            'price_per_day', 'deposit', 'condition',
            'address', 'city', 'latitude', 'longitude', 'status',
        ]

    def validate_status(self, value):
        # Owner can only toggle between active/inactive
        if value == Item.STATUS_MODERATION:
            raise serializers.ValidationError('Нельзя вручную установить статус "На модерации".')
        return value

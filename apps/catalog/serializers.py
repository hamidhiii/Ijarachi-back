from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from django.utils.dateparse import parse_date

from .models import Category, Favorite, Item, ItemImage, ItemAvailability
from core.schema import OwnerMiniSerializer


class CategorySerializer(serializers.ModelSerializer):
    """
    GET /categories/ — плоский список категорий с количеством объявлений.
    listings_count аннотируется в CategoryListView.get_queryset().
    """
    listings_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Category
        fields = ['id', 'name', 'name_uz', 'slug', 'icon', 'listings_count', 'attributes']


class CategoryMiniSerializer(serializers.ModelSerializer):
    """Вложенная категория внутри Listing: {id, name, name_uz, slug}."""

    class Meta:
        model = Category
        fields = ['id', 'name', 'name_uz', 'slug']


# ─── Item Images ──────────────────────────────────────────────────────────────

class ItemImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ItemImage
        fields = ['id', 'url', 'is_primary', 'order']
        read_only_fields = ['id']

    @extend_schema_field(serializers.URLField())
    def get_url(self, obj):
        request = self.context.get('request')
        return request.build_absolute_uri(obj.image.url) if request else obj.image.url


class ItemImageUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemImage
        fields = ['image', 'is_primary', 'order']


# ─── Item ─────────────────────────────────────────────────────────────────────

def validate_item_attributes(value):
    """
    Характеристики объявления — только скаляры (строка/число) и списки строк,
    без вложенных объектов (см. backend-integration: "attributes" contract).
    """
    if not isinstance(value, dict):
        raise serializers.ValidationError('attributes должен быть объектом.')
    for key, val in value.items():
        if not isinstance(key, str):
            raise serializers.ValidationError('Ключи attributes должны быть строками.')
        if isinstance(val, bool) or val is None:
            raise serializers.ValidationError(f'"{key}": допустимы только строка, число или список строк.')
        if isinstance(val, (str, int, float)):
            continue
        if isinstance(val, list) and all(isinstance(item, str) for item in val):
            continue
        raise serializers.ValidationError(f'"{key}": допустимы только строка, число или список строк.')
    return value


def _serialize_owner(item, request):
    try:
        profile = item.owner.profile
        return {
            'id': item.owner.id,
            'full_name': profile.full_name,
            'rating': profile.rating,
            'verified': bool(profile.is_verified_kyc),
        }
    except Exception:
        return {'id': item.owner.id, 'full_name': '', 'rating': 0, 'verified': False}


class ItemListSerializer(serializers.ModelSerializer):
    """Serializer for the /listings/ list — matches the frontend Listing contract."""
    category = CategoryMiniSerializer(read_only=True)
    images = ItemImageSerializer(many=True, read_only=True)
    owner = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    reviews_count = serializers.SerializerMethodField()
    is_favorite = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = [
            'id', 'title', 'description', 'category',
            'price_per_day', 'deposit', 'condition',
            'address', 'city', 'district', 'latitude', 'longitude', 'min_rental_days',
            'status', 'images', 'attributes', 'owner', 'rating', 'reviews_count',
            'view_count', 'favorite_count', 'is_favorite', 'created_at',
        ]

    @extend_schema_field(OwnerMiniSerializer)
    def get_owner(self, obj):
        return _serialize_owner(obj, self.context.get('request'))

    @extend_schema_field(serializers.FloatField())
    def get_rating(self, obj):
        from django.db.models import Avg
        value = obj.reviews.filter(reviewee=obj.owner).aggregate(avg=Avg('rating'))['avg']
        return round(value, 2) if value else 0

    @extend_schema_field(serializers.IntegerField())
    def get_reviews_count(self, obj):
        return obj.reviews.filter(reviewee=obj.owner).count()

    @extend_schema_field(serializers.BooleanField())
    def get_is_favorite(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        return Favorite.objects.filter(user=user, item=obj).exists()


class ItemDetailSerializer(serializers.ModelSerializer):
    """Full serializer for single item view — matches the frontend Listing contract."""
    images = ItemImageSerializer(many=True, read_only=True)
    category = CategoryMiniSerializer(read_only=True)
    blocked_dates = serializers.SerializerMethodField()
    owner = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    reviews_count = serializers.SerializerMethodField()
    is_favorite = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = [
            'id', 'title', 'description', 'price_per_day', 'deposit',
            'condition', 'status', 'city', 'district', 'address', 'latitude', 'longitude',
            'category', 'images', 'attributes', 'blocked_dates', 'owner', 'created_at',
            'view_count', 'favorite_count', 'min_rental_days',
            'is_favorite', 'rating', 'reviews_count',
        ]

    @extend_schema_field(serializers.ListField(child=serializers.CharField(), help_text='YYYY-MM-DD'))
    def get_blocked_dates(self, obj):
        try:
            return obj.availability.blocked_dates
        except ItemAvailability.DoesNotExist:
            return []

    @extend_schema_field(OwnerMiniSerializer)
    def get_owner(self, obj):
        return _serialize_owner(obj, self.context.get('request'))

    @extend_schema_field(serializers.FloatField())
    def get_rating(self, obj):
        from django.db.models import Avg
        value = obj.reviews.filter(reviewee=obj.owner).aggregate(avg=Avg('rating'))['avg']
        return round(value, 2) if value else 0

    @extend_schema_field(serializers.IntegerField())
    def get_reviews_count(self, obj):
        return obj.reviews.filter(reviewee=obj.owner).count()

    @extend_schema_field(serializers.BooleanField())
    def get_is_favorite(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        return Favorite.objects.filter(user=user, item=obj).exists()


class ItemCreateSerializer(serializers.ModelSerializer):
    attributes = serializers.JSONField(required=False, default=dict)

    class Meta:
        model = Item
        fields = [
            'title', 'description', 'category',
            'price_per_day', 'deposit', 'condition',
            'address', 'city', 'district', 'latitude', 'longitude', 'min_rental_days',
            'attributes',
        ]

    def validate_price_per_day(self, value):
        if value <= 0:
            raise serializers.ValidationError('Цена должна быть больше нуля.')
        return value

    def validate_deposit(self, value):
        if value < 0:
            raise serializers.ValidationError('Залог не может быть отрицательным.')
        return value

    def validate_attributes(self, value):
        return validate_item_attributes(value)

    def create(self, validated_data):
        user = self.context['request'].user
        item = Item.objects.create(owner=user, status=Item.STATUS_PENDING, **validated_data)
        # Create empty availability record
        ItemAvailability.objects.create(item=item)
        return item


class ItemUpdateSerializer(serializers.ModelSerializer):
    attributes = serializers.JSONField(required=False)

    class Meta:
        model = Item
        fields = [
            'title', 'description', 'category',
            'price_per_day', 'deposit', 'condition',
            'address', 'city', 'district', 'latitude', 'longitude', 'min_rental_days', 'status',
            'attributes',
        ]

    def validate_attributes(self, value):
        return validate_item_attributes(value)

    def validate_status(self, value):
        request = self.context.get('request')
        if request and request.user and request.user.is_staff:
            return value
        if value not in [Item.STATUS_INACTIVE, Item.STATUS_PENDING]:
            raise serializers.ValidationError('Владелец может снять объявление или отправить его на повторную модерацию.')
        return value


class ListingModerationSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[
        (Item.STATUS_APPROVED, 'approved'),
        (Item.STATUS_REJECTED, 'rejected'),
    ])
    rejection_reason = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs['status'] == Item.STATUS_REJECTED and not attrs.get('rejection_reason'):
            raise serializers.ValidationError({'rejection_reason': 'Укажите причину отклонения.'})
        return attrs


class ListingStatsSerializer(serializers.Serializer):
    listing_id = serializers.IntegerField()
    views = serializers.IntegerField()
    favorites = serializers.IntegerField()
    deals = serializers.IntegerField()


class ListingAvailabilitySerializer(serializers.Serializer):
    blocked_dates = serializers.ListField(child=serializers.CharField(), required=False)
    blockedDates = serializers.ListField(child=serializers.CharField(), required=False, write_only=True)

    def validate(self, attrs):
        raw_dates = attrs.get('blocked_dates', attrs.get('blockedDates', []))
        normalized = []
        for value in raw_dates:
            parsed = parse_date(str(value))
            if not parsed:
                raise serializers.ValidationError({'blocked_dates': f'Invalid date: {value}'})
            normalized.append(parsed.isoformat())
        attrs['blocked_dates'] = sorted(set(normalized))
        return attrs


class FavoriteCreateSerializer(serializers.Serializer):
    listing_id = serializers.IntegerField(required=False)
    listing = serializers.IntegerField(required=False)

    def validate(self, attrs):
        listing_id = attrs.get('listing_id') or attrs.get('listing')
        if not listing_id:
            raise serializers.ValidationError({'listing_id': 'This field is required.'})
        try:
            item = Item.objects.get(pk=listing_id, status=Item.STATUS_APPROVED)
        except Item.DoesNotExist:
            raise serializers.ValidationError({'listing_id': 'Listing not found.'})
        attrs['item'] = item
        return attrs

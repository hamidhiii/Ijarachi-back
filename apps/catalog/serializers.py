from rest_framework import serializers
from django.utils.dateparse import parse_date

from .models import Category, Favorite, Item, ItemImage, ItemAvailability


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
    is_favorite = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = [
            'id', 'title', 'price_per_day', 'deposit',
            'condition', 'status', 'city', 'address',
            'category_name', 'primary_image',
            'owner_name', 'view_count', 'favorite_count',
            'is_favorite', 'review_count', 'average_rating', 'created_at',
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

    def get_is_favorite(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        return Favorite.objects.filter(user=user, item=obj).exists()

    def get_review_count(self, obj):
        return obj.reviews.filter(reviewee=obj.owner).count()

    def get_average_rating(self, obj):
        from django.db.models import Avg
        value = obj.reviews.filter(reviewee=obj.owner).aggregate(avg=Avg('rating'))['avg']
        return round(value, 2) if value else 0


class ItemDetailSerializer(serializers.ModelSerializer):
    """Full serializer for single item view."""
    images = ItemImageSerializer(many=True, read_only=True)
    category = CategoryFlatSerializer(read_only=True)
    blocked_dates = serializers.SerializerMethodField()
    owner = serializers.SerializerMethodField()
    is_favorite = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = [
            'id', 'title', 'description', 'price_per_day', 'deposit',
            'condition', 'status', 'city', 'address', 'latitude', 'longitude',
            'category', 'images', 'blocked_dates', 'owner', 'created_at',
            'view_count', 'favorite_count', 'min_rental_days',
            'is_favorite', 'review_count', 'average_rating',
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

    def get_is_favorite(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        return Favorite.objects.filter(user=user, item=obj).exists()

    def get_review_count(self, obj):
        return obj.reviews.filter(reviewee=obj.owner).count()

    def get_average_rating(self, obj):
        from django.db.models import Avg
        value = obj.reviews.filter(reviewee=obj.owner).aggregate(avg=Avg('rating'))['avg']
        return round(value, 2) if value else 0


class ItemCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Item
        fields = [
            'title', 'description', 'category',
            'price_per_day', 'deposit', 'condition',
            'address', 'city', 'latitude', 'longitude', 'min_rental_days',
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
        item = Item.objects.create(owner=user, status=Item.STATUS_PENDING, **validated_data)
        # Create empty availability record
        ItemAvailability.objects.create(item=item)
        return item


class ItemUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Item
        fields = [
            'title', 'description', 'category',
            'price_per_day', 'deposit', 'condition',
            'address', 'city', 'latitude', 'longitude', 'min_rental_days', 'status',
        ]

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


class FavoriteSerializer(serializers.ModelSerializer):
    listing_id = serializers.IntegerField(source='item_id', read_only=True)
    listing = ItemListSerializer(source='item', read_only=True)

    class Meta:
        model = Favorite
        fields = ['id', 'listing_id', 'listing', 'created_at']
        read_only_fields = fields


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

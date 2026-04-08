from decimal import Decimal
from django.conf import settings
from rest_framework import serializers
from .models import Booking, VerificationPhoto
from apps.catalog.models import Item


class BookingCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = ['item', 'start_date', 'end_date', 'renter_comment']

    def validate(self, data):
        item = data['item']
        start = data['start_date']
        end = data['end_date']

        if start > end:
            raise serializers.ValidationError('Дата начала не может быть позже даты окончания.')

        if item.status != Item.STATUS_ACTIVE:
            raise serializers.ValidationError('Эта вещь недоступна для аренды.')

        if item.owner == self.context['request'].user:
            raise serializers.ValidationError('Нельзя арендовать собственную вещь.')

        # Check availability
        try:
            if not item.availability.is_available(start, end):
                raise serializers.ValidationError('Выбранные даты уже заняты.')
        except item.availability.RelatedObjectDoesNotExist:
            pass  # No availability record = all dates free

        return data

    def create(self, validated_data):
        from django.conf import settings
        item = validated_data['item']
        start = validated_data['start_date']
        end = validated_data['end_date']
        days = (end - start).days + 1

        commission_pct = Decimal(settings.PLATFORM_COMMISSION_PERCENT) / 100
        rental_cost = item.price_per_day * days
        commission = (rental_cost * commission_pct).quantize(Decimal('1'))
        total = rental_cost + commission + item.deposit

        booking = Booking.objects.create(
            renter=self.context['request'].user,
            item=item,
            start_date=start,
            end_date=end,
            price_per_day=item.price_per_day,
            deposit_amount=item.deposit,
            commission_amount=commission,
            total_price=total,
            renter_comment=validated_data.get('renter_comment', ''),
            status=Booking.STATUS_CREATED,
        )
        return booking


class BookingListSerializer(serializers.ModelSerializer):
    item_title = serializers.CharField(source='item.title', read_only=True)
    item_id = serializers.IntegerField(source='item.id', read_only=True)
    renter_phone = serializers.CharField(source='renter.phone', read_only=True)
    days = serializers.IntegerField(read_only=True)

    class Meta:
        model = Booking
        fields = [
            'id', 'item_id', 'item_title', 'renter_phone',
            'start_date', 'end_date', 'days',
            'price_per_day', 'deposit_amount', 'commission_amount', 'total_price',
            'status', 'created_at',
        ]


class BookingDetailSerializer(serializers.ModelSerializer):
    days = serializers.IntegerField(read_only=True)
    photos = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            'id', 'item', 'renter',
            'start_date', 'end_date', 'days',
            'price_per_day', 'deposit_amount', 'commission_amount', 'total_price',
            'status', 'renter_comment', 'photos', 'created_at', 'updated_at',
        ]
        read_only_fields = ['renter', 'price_per_day', 'deposit_amount', 'commission_amount', 'total_price']

    def get_photos(self, obj):
        return VerificationPhotoSerializer(obj.verification_photos.all(), many=True, context=self.context).data


class BookingStatusUpdateSerializer(serializers.Serializer):
    """For status transitions by owner or renter."""
    ALLOWED_TRANSITIONS = {
        (Booking.STATUS_CREATED, 'renter'): [Booking.STATUS_CANCELLED],
        (Booking.STATUS_WAITING_OWNER, 'owner'): [Booking.STATUS_WAITING_RENTER, Booking.STATUS_CANCELLED],
        (Booking.STATUS_WAITING_RENTER, 'renter'): [Booking.STATUS_IN_RENT, Booking.STATUS_DISPUTE],
        (Booking.STATUS_IN_RENT, 'renter'): [Booking.STATUS_RETURNING],
        (Booking.STATUS_RETURNING, 'owner'): [Booking.STATUS_INSPECTION, Booking.STATUS_DISPUTE],
        (Booking.STATUS_INSPECTION, 'owner'): [Booking.STATUS_COMPLETED, Booking.STATUS_DISPUTE],
    }

    status = serializers.ChoiceField(choices=Booking.STATUS_CHOICES)

    def validate_status(self, new_status):
        booking = self.context['booking']
        user = self.context['request'].user

        role = None
        if user == booking.renter:
            role = 'renter'
        elif user == booking.item.owner:
            role = 'owner'
        else:
            raise serializers.ValidationError('У вас нет доступа к этому бронированию.')

        allowed = self.ALLOWED_TRANSITIONS.get((booking.status, role), [])
        if new_status not in allowed:
            raise serializers.ValidationError(
                f'Переход из "{booking.status}" в "{new_status}" не разрешён для роли "{role}".'
            )
            
        # Checks for Minimum 5 photos
        if new_status == Booking.STATUS_WAITING_RENTER:
            count = booking.verification_photos.filter(photo_type=VerificationPhoto.TYPE_OWNER_START).count()
            if count < 5:
                raise serializers.ValidationError(f'Для передачи требуется минимум 5 фото от владельца. Загружено: {count}.')
                
        if new_status == Booking.STATUS_IN_RENT:
            count = booking.verification_photos.filter(photo_type=VerificationPhoto.TYPE_RENTER_START).count()
            if count < 5:
                raise serializers.ValidationError(f'Для старта аренды требуется минимум 5 фото от арендатора. Загружено: {count}.')
                
        if new_status == Booking.STATUS_RETURNING:
            count = booking.verification_photos.filter(photo_type=VerificationPhoto.TYPE_RENTER_END).count()
            if count < 5:
                raise serializers.ValidationError(f'Для возврата требуется минимум 5 фото ПОСЛЕ от арендатора. Загружено: {count}.')

        return new_status


class VerificationPhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationPhoto
        fields = ['id', 'photo_type', 'image', 'file_hash', 'metadata', 'uploaded_at', 'comment']
        read_only_fields = ['id', 'file_hash', 'uploaded_at']


class VerificationPhotoUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationPhoto
        fields = ['photo_type', 'image', 'metadata', 'comment']

    def validate_metadata(self, value):
        required_keys = {'lat', 'lng', 'device_time'}
        if not required_keys.issubset(value.keys()):
            raise serializers.ValidationError(f'Метаданные должны содержать: {required_keys}')
        return value

    def validate(self, data):
        booking = self.context['booking']
        photo_type = data['photo_type']

        valid_map = {
            VerificationPhoto.TYPE_OWNER_START: Booking.STATUS_WAITING_OWNER,
            VerificationPhoto.TYPE_RENTER_START: Booking.STATUS_WAITING_RENTER,
            VerificationPhoto.TYPE_RENTER_END: Booking.STATUS_IN_RENT,
            VerificationPhoto.TYPE_OWNER_END: [Booking.STATUS_RETURNING, Booking.STATUS_INSPECTION, Booking.STATUS_DISPUTE],
        }
        
        allowed_status = valid_map.get(photo_type)
        if isinstance(allowed_status, list):
            if booking.status not in allowed_status:
                raise serializers.ValidationError(f'Фото "{photo_type}" нельзя загружать на этапе "{booking.status}".')
        else:
            if booking.status != allowed_status:
                raise serializers.ValidationError(f'Фото "{photo_type}" можно загрузить только на этапе "{allowed_status}".')

        return data

    def create(self, validated_data):
        import hashlib
        image = validated_data['image']
        
        # Calculate SHA-256 Hash
        sha256_hash = hashlib.sha256()
        for chunk in image.chunks():
            sha256_hash.update(chunk)
        
        validated_data['file_hash'] = sha256_hash.hexdigest()

        return VerificationPhoto.objects.create(
            booking=self.context['booking'],
            uploaded_by=self.context['request'].user,
            **validated_data,
        )

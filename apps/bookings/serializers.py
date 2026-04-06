from decimal import Decimal
from django.conf import settings
from rest_framework import serializers
from .models import Booking, PhotoProtocol
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
            status=Booking.STATUS_WAITING_PAYMENT,
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
        return PhotoProtocolSerializer(obj.photos.all(), many=True, context=self.context).data


class BookingStatusUpdateSerializer(serializers.Serializer):
    """For status transitions by owner or renter."""
    ALLOWED_TRANSITIONS = {
        # (current_status, role) → allowed next statuses
        (Booking.STATUS_WAITING_PAYMENT, 'renter'): [Booking.STATUS_CANCELLED],
        (Booking.STATUS_PAID_ESCROW, 'owner'): [Booking.STATUS_ACTIVE],
        (Booking.STATUS_ACTIVE, 'owner'): [Booking.STATUS_RETURNING],
        (Booking.STATUS_RETURNING, 'renter'): [Booking.STATUS_COMPLETED, Booking.STATUS_DISPUTE],
        (Booking.STATUS_RETURNING, 'owner'): [Booking.STATUS_DISPUTE],
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
        return new_status


class PhotoProtocolSerializer(serializers.ModelSerializer):
    class Meta:
        model = PhotoProtocol
        fields = ['id', 'photo_type', 'image', 'uploaded_at', 'comment']
        read_only_fields = ['id', 'uploaded_at']


class PhotoProtocolUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = PhotoProtocol
        fields = ['photo_type', 'image', 'comment']

    def validate(self, data):
        booking = self.context['booking']
        photo_type = data['photo_type']

        if photo_type == PhotoProtocol.TYPE_BEFORE and booking.status != Booking.STATUS_PAID_ESCROW:
            raise serializers.ValidationError('Фото "до" можно загрузить только при статусе "paid_escrow".')
        if photo_type == PhotoProtocol.TYPE_AFTER and booking.status != Booking.STATUS_RETURNING:
            raise serializers.ValidationError('Фото "после" можно загрузить только при статусе "returning".')
        return data

    def create(self, validated_data):
        return PhotoProtocol.objects.create(
            booking=self.context['booking'],
            uploaded_by=self.context['request'].user,
            **validated_data,
        )

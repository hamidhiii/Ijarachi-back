from decimal import Decimal
from rest_framework import serializers
from .models import Booking, Deliverer
from apps.catalog.models import Item

PLATFORM_COMMISSION = Decimal('0.15')


class BookingCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = [
            'item', 'start_date', 'end_date',
            'delivery_address', 'delivery_lat', 'delivery_lng',
            'renter_comment',
        ]

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

        try:
            if not item.availability.is_available(start, end):
                raise serializers.ValidationError('Выбранные даты уже заняты.')
        except Item.availability.RelatedObjectDoesNotExist:
            pass

        return data

    def create(self, validated_data):
        item = validated_data['item']
        start = validated_data['start_date']
        end = validated_data['end_date']
        days = (end - start).days + 1

        rental_cost = item.price_per_day * days
        commission = (rental_cost * PLATFORM_COMMISSION).quantize(Decimal('1'))
        total = rental_cost + commission + item.deposit

        return Booking.objects.create(
            renter=self.context['request'].user,
            item=item,
            start_date=start,
            end_date=end,
            price_per_day=item.price_per_day,
            deposit_amount=item.deposit,
            commission_amount=commission,
            total_price=total,
            delivery_address=validated_data.get('delivery_address', ''),
            delivery_lat=validated_data.get('delivery_lat'),
            delivery_lng=validated_data.get('delivery_lng'),
            renter_comment=validated_data.get('renter_comment', ''),
            status=Booking.STATUS_PAYMENT_PENDING,
        )


class DelivererSerializer(serializers.ModelSerializer):
    class Meta:
        model = Deliverer
        fields = ['id', 'name', 'phone']


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
            'total_price', 'status', 'created_at',
        ]


class BookingDetailSerializer(serializers.ModelSerializer):
    days = serializers.IntegerField(read_only=True)
    deliverer = DelivererSerializer(read_only=True)
    owner_phone = serializers.CharField(source='item.owner.phone', read_only=True)
    item_title = serializers.CharField(source='item.title', read_only=True)
    progress_renter = serializers.SerializerMethodField()
    progress_owner = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            'id', 'item', 'item_title', 'renter', 'owner_phone',
            'start_date', 'end_date', 'days',
            'price_per_day', 'deposit_amount', 'commission_amount', 'total_price',
            'delivery_address', 'delivery_lat', 'delivery_lng',
            'deliverer', 'pickup_eta', 'delivery_eta',
            'status', 'progress_renter', 'progress_owner',
            'renter_comment', 'created_at', 'updated_at',
        ]
        read_only_fields = ['renter', 'price_per_day', 'deposit_amount', 'commission_amount', 'total_price']

    def get_progress_renter(self, obj) -> str:
        return obj.progress_for('renter')

    def get_progress_owner(self, obj) -> str:
        return obj.progress_for('owner')


class AssignDelivererSerializer(serializers.Serializer):
    """Admin-only: assign a deliverer and set ETAs."""
    deliverer_id = serializers.IntegerField()
    pickup_eta = serializers.DateTimeField()
    delivery_eta = serializers.DateTimeField()

    def validate_deliverer_id(self, value):
        try:
            return Deliverer.objects.get(pk=value, is_active=True)
        except Deliverer.DoesNotExist:
            raise serializers.ValidationError('Доставщик не найден или неактивен.')

    def validate(self, data):
        if data['pickup_eta'] >= data['delivery_eta']:
            raise serializers.ValidationError('ETA к арендатору должна быть позже ETA к владельцу.')
        return data


class BookingStatusUpdateSerializer(serializers.Serializer):
    """Status transitions based on role."""
    # (current_status, role) → allowed next statuses
    ALLOWED_TRANSITIONS = {
        (Booking.STATUS_PLACED, 'renter'): [Booking.STATUS_CANCELLED],
        (Booking.STATUS_PICKUP_SCHEDULED, 'deliverer'): [Booking.STATUS_PICKED_UP],
        (Booking.STATUS_PICKED_UP, 'deliverer'): [Booking.STATUS_ACTIVE],
        (Booking.STATUS_ACTIVE, 'owner'): [Booking.STATUS_COMPLETED],
        (Booking.STATUS_ACTIVE, 'renter'): [Booking.STATUS_COMPLETED],
    }

    status = serializers.ChoiceField(choices=Booking.STATUS_CHOICES)

    def validate_status(self, new_status):
        booking = self.context['booking']
        user = self.context['request'].user

        role = self._resolve_role(booking, user)
        if not role:
            raise serializers.ValidationError('У вас нет доступа к этому бронированию.')

        allowed = self.ALLOWED_TRANSITIONS.get((booking.status, role), [])
        if new_status not in allowed:
            raise serializers.ValidationError(
                f'Переход из "{booking.status}" в "{new_status}" не разрешён.'
            )
        return new_status

    def _resolve_role(self, booking, user):
        if user.is_staff:
            return 'admin'
        if user == booking.renter:
            return 'renter'
        if user == booking.item.owner:
            return 'owner'
        try:
            if user == booking.deliverer.user:  # noqa: if Deliverer gets a user FK
                return 'deliverer'
        except Exception:
            pass
        return None

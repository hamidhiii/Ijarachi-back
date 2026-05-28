from decimal import Decimal

from django.conf import settings
from rest_framework import serializers

from .models import Booking, Deliverer
from apps.catalog.models import Item


def platform_commission_rate() -> Decimal:
    return Decimal(str(settings.PLATFORM_COMMISSION_PERCENT)) / Decimal('100')


class BookingCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = [
            'item',
            'start_date',
            'end_date',
            'delivery_method',
            'delivery_cost',
            'delivery_address',
            'delivery_lat',
            'delivery_lng',
            'delivery_comment',
            'renter_comment',
        ]

    def validate(self, data):
        item = data['item']
        start = data['start_date']
        end = data['end_date']

        if start > end:
            raise serializers.ValidationError('Дата начала не может быть позже даты окончания.')

        if item.status != Item.STATUS_APPROVED:
            raise serializers.ValidationError('Эта вещь недоступна для аренды.')

        if item.owner == self.context['request'].user:
            raise serializers.ValidationError('Нельзя арендовать собственную вещь.')

        if data.get('delivery_method') == Booking.DELIVERY_DELIVERY and not data.get('delivery_address'):
            raise serializers.ValidationError({'delivery_address': 'Укажите адрес доставки.'})

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
        commission = (rental_cost * platform_commission_rate()).quantize(Decimal('1'))
        delivery_cost = validated_data.get('delivery_cost') or Decimal('0')
        total = rental_cost + commission + item.deposit + delivery_cost
        initial_status = self.context.get('initial_status', Booking.STATUS_DRAFT)

        return Booking.objects.create(
            renter=self.context['request'].user,
            item=item,
            start_date=start,
            end_date=end,
            price_per_day=item.price_per_day,
            deposit_amount=item.deposit,
            commission_amount=commission,
            delivery_cost=delivery_cost,
            total_price=total,
            delivery_method=validated_data.get('delivery_method', Booking.DELIVERY_PICKUP),
            delivery_address=validated_data.get('delivery_address', ''),
            delivery_lat=validated_data.get('delivery_lat'),
            delivery_lng=validated_data.get('delivery_lng'),
            delivery_comment=validated_data.get('delivery_comment', ''),
            renter_comment=validated_data.get('renter_comment', ''),
            escrow_amount=total,
            status=initial_status,
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
            'id',
            'item_id',
            'item_title',
            'renter_phone',
            'start_date',
            'end_date',
            'days',
            'delivery_method',
            'delivery_cost',
            'total_price',
            'status',
            'escrow_status',
            'created_at',
        ]


class BookingDetailSerializer(serializers.ModelSerializer):
    days = serializers.IntegerField(read_only=True)
    deliverer = DelivererSerializer(read_only=True)
    owner_phone = serializers.SerializerMethodField()
    owner_contact = serializers.SerializerMethodField()
    item_title = serializers.CharField(source='item.title', read_only=True)
    progress_renter = serializers.SerializerMethodField()
    progress_owner = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            'id',
            'item',
            'item_title',
            'renter',
            'owner_phone',
            'owner_contact',
            'start_date',
            'end_date',
            'days',
            'price_per_day',
            'deposit_amount',
            'commission_amount',
            'delivery_cost',
            'total_price',
            'delivery_method',
            'delivery_address',
            'delivery_lat',
            'delivery_lng',
            'delivery_comment',
            'deliverer',
            'pickup_eta',
            'delivery_eta',
            'yandex_delivery_order_id',
            'yandex_delivery_status',
            'status',
            'escrow_status',
            'escrow_amount',
            'progress_renter',
            'progress_owner',
            'renter_comment',
            'dispute_reason',
            'returned_at',
            'contact_revealed_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'renter',
            'price_per_day',
            'deposit_amount',
            'commission_amount',
            'delivery_cost',
            'total_price',
            'escrow_status',
            'escrow_amount',
        ]

    def get_progress_renter(self, obj) -> str:
        return obj.progress_for('renter')

    def get_progress_owner(self, obj) -> str:
        return obj.progress_for('owner')

    def get_owner_contact(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        can_view = (
            user
            and user.is_authenticated
            and (
                user == obj.item.owner
                or (
                    user == obj.renter
                    and obj.delivery_method == Booking.DELIVERY_PICKUP
                    and obj.status in [
                        Booking.STATUS_PAID,
                        Booking.STATUS_IN_PROGRESS,
                        Booking.STATUS_RETURNED,
                        Booking.STATUS_COMPLETED,
                    ]
                )
            )
        )
        if not can_view:
            return None
        return {
            'phone': obj.item.owner.phone,
            'address': obj.item.address,
            'latitude': obj.item.latitude,
            'longitude': obj.item.longitude,
        }

    def get_owner_phone(self, obj):
        contact = self.get_owner_contact(obj)
        return contact['phone'] if contact else None


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
    ALLOWED_TRANSITIONS = {
        (Booking.STATUS_DRAFT, 'renter'): [Booking.STATUS_CANCELLED],
        (Booking.STATUS_PENDING_PAYMENT, 'renter'): [Booking.STATUS_CANCELLED],
        (Booking.STATUS_PAID, 'renter'): [Booking.STATUS_CANCELLED, Booking.STATUS_IN_PROGRESS],
        (Booking.STATUS_PAID, 'owner'): [Booking.STATUS_IN_PROGRESS],
        (Booking.STATUS_IN_PROGRESS, 'renter'): [Booking.STATUS_RETURNED, Booking.STATUS_DISPUTED],
        (Booking.STATUS_IN_PROGRESS, 'owner'): [Booking.STATUS_DISPUTED],
        (Booking.STATUS_RETURNED, 'owner'): [Booking.STATUS_COMPLETED],
    }

    status = serializers.ChoiceField(choices=Booking.STATUS_CHOICES)

    def validate_status(self, new_status):
        booking = self.context['booking']
        user = self.context['request'].user

        role = self._resolve_role(booking, user)
        if not role:
            raise serializers.ValidationError('У вас нет доступа к этой сделке.')

        allowed = self.ALLOWED_TRANSITIONS.get((booking.status, role), [])
        if user.is_staff:
            allowed = [choice[0] for choice in Booking.STATUS_CHOICES]
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
        return None


class DealPaySerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=['click', 'payme'])


class DeliveryCalculationSerializer(serializers.Serializer):
    from_lat = serializers.FloatField(required=False)
    from_lng = serializers.FloatField(required=False)
    to_lat = serializers.FloatField()
    to_lng = serializers.FloatField()


class DisputeSerializer(serializers.Serializer):
    reason = serializers.CharField()

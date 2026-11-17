from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.models import Item

from .models import Branch, Client, Reservation, StaffMember


class BranchSerializer(serializers.ModelSerializer):
    listings_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Branch
        fields = ['id', 'name', 'address', 'phone', 'is_active', 'listings_count', 'created_at']
        read_only_fields = ['id', 'created_at']


class StaffMemberSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(write_only=True, help_text='Номер пользователя Rentoo')
    user_id = serializers.IntegerField(read_only=True)
    user_phone = serializers.CharField(source='user.phone', read_only=True)
    name = serializers.SerializerMethodField()

    class Meta:
        model = StaffMember
        fields = ['id', 'phone', 'user_id', 'user_phone', 'name', 'role', 'created_at']
        read_only_fields = ['id', 'created_at']

    @extend_schema_field(serializers.CharField())
    def get_name(self, obj):
        profile = getattr(obj.user, 'profile', None)
        return profile.full_name if profile else ''

    def validate_phone(self, value):
        user = get_user_model().objects.filter(phone=value.strip(), is_active=True).first()
        if user is None:
            raise serializers.ValidationError('Пользователь с таким номером не найден — пусть сначала войдёт в Rentoo.')
        return user


class StaffRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffMember
        fields = ['role']


class ClientSerializer(serializers.ModelSerializer):
    rentoo_user_id = serializers.IntegerField(source='user_id', read_only=True, allow_null=True)
    reservations_count = serializers.IntegerField(read_only=True, default=0)
    last_reservation = serializers.DateField(read_only=True, default=None, allow_null=True)

    class Meta:
        model = Client
        fields = [
            'id', 'name', 'phone', 'notes', 'rentoo_user_id',
            'reservations_count', 'last_reservation', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ReservationClientSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    phone = serializers.CharField()


class ReservationSerializer(serializers.ModelSerializer):
    """
    listing — объявление своего аккаунта. Клиент: `client` (id из базы) или
    `client_name` + `client_phone` — новый клиент (или найденный по телефону).
    """
    listing = serializers.PrimaryKeyRelatedField(source='item', queryset=Item.objects.none())
    listing_title = serializers.CharField(source='item.title', read_only=True)
    client = serializers.PrimaryKeyRelatedField(queryset=Client.objects.none(), required=False, allow_null=True)
    client_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    client_phone = serializers.CharField(write_only=True, required=False, allow_blank=True)
    client_info = serializers.SerializerMethodField()

    class Meta:
        model = Reservation
        fields = [
            'id', 'listing', 'listing_title', 'quantity', 'start_date', 'end_date',
            'source', 'status', 'price', 'notes',
            'client', 'client_name', 'client_phone', 'client_info',
            'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        account = self.context.get('account')
        if account is not None:
            self.fields['listing'].queryset = Item.objects.filter(owner=account)
            self.fields['client'].queryset = Client.objects.filter(owner=account)

    @extend_schema_field(ReservationClientSerializer(allow_null=True))
    def get_client_info(self, obj):
        if obj.client_id is None:
            return None
        return {'id': obj.client_id, 'name': obj.client.name, 'phone': obj.client.phone}


class ClientDetailSerializer(ClientSerializer):
    """Карточка клиента: контакты, заметки и история аренд."""
    history = serializers.SerializerMethodField()

    class Meta(ClientSerializer.Meta):
        fields = ClientSerializer.Meta.fields + ['history']

    @extend_schema_field(ReservationSerializer(many=True))
    def get_history(self, obj):
        reservations = obj.reservations.select_related('item').order_by('-start_date', '-pk')
        return ReservationSerializer(reservations, many=True, context=self.context).data


class OwnerListingSerializer(serializers.ModelSerializer):
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.none(), allow_null=True, required=False)
    free_today = serializers.IntegerField(read_only=True)

    class Meta:
        model = Item
        fields = ['id', 'title', 'status', 'quantity', 'price_per_day', 'branch', 'free_today']
        read_only_fields = ['id', 'title', 'status', 'quantity', 'price_per_day']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        account = self.context.get('account')
        if account is not None:
            self.fields['branch'].queryset = Branch.objects.filter(owner=account)


class CalendarDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    booked = serializers.IntegerField()
    free = serializers.IntegerField()
    blocked = serializers.BooleanField(help_text='Закрыт владельцем вручную')


class ListingCalendarSerializer(serializers.Serializer):
    listing = serializers.IntegerField()
    title = serializers.CharField()
    quantity = serializers.IntegerField()
    days = CalendarDaySerializer(many=True)
    reservations = ReservationSerializer(many=True)


class StockRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    branch = serializers.IntegerField(allow_null=True)
    quantity = serializers.IntegerField()
    booked = serializers.IntegerField()
    free = serializers.IntegerField()


class StatsRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    status = serializers.CharField()
    views = serializers.IntegerField()
    phone_reveals = serializers.IntegerField()
    chat_messages = serializers.IntegerField()


class StatsResponseSerializer(serializers.Serializer):
    month = serializers.CharField()
    totals = serializers.DictField(child=serializers.IntegerField())
    listings = StatsRowSerializer(many=True)
    by_month = serializers.ListField(child=serializers.DictField())


class AccountSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    role = serializers.CharField()
    plan = serializers.CharField()

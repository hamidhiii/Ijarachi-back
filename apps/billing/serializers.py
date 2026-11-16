from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import BillingOrder, Plan


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            'code', 'name', 'price', 'listing_limit', 'search_priority',
            'staff_access', 'statistics', 'branches', 'data_export', 'rank',
        ]


class SubscriptionStateSerializer(serializers.Serializer):
    """GET /billing/subscription/ — что действует сейчас."""
    plan = PlanSerializer()
    is_paid = serializers.BooleanField()
    ends_at = serializers.DateTimeField(allow_null=True)
    days_left = serializers.IntegerField(allow_null=True)
    listing_limit = serializers.IntegerField(allow_null=True)
    live_listings = serializers.IntegerField()
    paused_listings = serializers.IntegerField(help_text='Снято по окончании тарифа, вернутся после оплаты')


class OrderSerializer(serializers.ModelSerializer):
    plan = serializers.SlugRelatedField(slug_field='code', read_only=True)
    listing = serializers.IntegerField(source='item_id', read_only=True, allow_null=True)
    title = serializers.CharField(read_only=True)

    class Meta:
        model = BillingOrder
        fields = [
            'id', 'kind', 'plan', 'promotion', 'listing', 'title', 'amount',
            'status', 'provider', 'created_at', 'paid_at',
        ]
        read_only_fields = fields


class OrderCreatedSerializer(OrderSerializer):
    redirect_url = serializers.SerializerMethodField()

    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + ['redirect_url']
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_redirect_url(self, obj):
        return self.context.get('redirect_url')


class OrderCreateSerializer(serializers.Serializer):
    """
    POST /billing/orders/: {"kind": "plan", "plan": "start", "provider": "click"}
    или {"kind": "promotion", "promotion": "top", "listing": 12, "provider": "payme"}.
    """
    kind = serializers.ChoiceField(choices=[c for c, _ in BillingOrder.KIND_CHOICES], default=BillingOrder.KIND_PLAN)
    plan = serializers.SlugRelatedField(
        slug_field='code', queryset=Plan.objects.filter(is_active=True), required=False,
    )
    promotion = serializers.ChoiceField(choices=[c for c, _ in BillingOrder.PROMO_CHOICES], required=False)
    listing = serializers.IntegerField(required=False)
    provider = serializers.ChoiceField(choices=[BillingOrder.PROVIDER_CLICK, BillingOrder.PROVIDER_PAYME])

    def validate(self, attrs):
        from .services import check_can_buy

        user = self.context['request'].user
        if attrs['kind'] == BillingOrder.KIND_PLAN:
            plan = attrs.get('plan')
            if plan is None:
                raise serializers.ValidationError({'plan': 'Выберите тариф.'})
            check_can_buy(user, plan)
            attrs['amount'] = plan.price
        else:
            from .promotions import validate_promotion_order
            attrs.update(validate_promotion_order(user, attrs))
        return attrs


def days_left(ends_at):
    if ends_at is None:
        return None
    return max((timezone.localdate(ends_at) - timezone.localdate()).days, 0)

"""
Админ-API тарифов (is_staff): подписки, платежи, ручное продление, метрики.

Метрики:
- платящие — пользователи с действующим платным тарифом, по тарифам;
- MRR — сумма месячных цен их тарифов (выданные вручную тоже: так продлевают
  после оплаты вне Click/Payme);
- отток за период — доля тех, у кого платный тариф действовал в начале
  периода, а сейчас не действует;
- выручка — оплаченные заказы за период без заглушки.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, DecimalField, Min, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BillingOrder, Plan, Subscription, SubscriptionPeriod
from .services import extend_subscription, restore_paused_listings


class AdminSubscriptionSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(read_only=True)
    phone = serializers.CharField(source='user.phone', read_only=True)
    plan = serializers.CharField(source='plan.code', read_only=True)
    is_active = serializers.SerializerMethodField()
    paid_total = serializers.DecimalField(max_digits=14, decimal_places=0, read_only=True, default=0)

    class Meta:
        model = Subscription
        fields = ['id', 'user_id', 'phone', 'plan', 'ends_at', 'is_active', 'paid_total', 'created_at']

    def get_is_active(self, obj) -> bool:
        return obj.ends_at > timezone.now()


class AdminOrderSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(source='user.phone', read_only=True)
    plan = serializers.CharField(source='plan.code', read_only=True, default=None)
    listing = serializers.IntegerField(source='item_id', read_only=True, allow_null=True)

    class Meta:
        model = BillingOrder
        fields = [
            'id', 'user_id', 'phone', 'kind', 'plan', 'promotion', 'listing', 'amount', 'provider',
            'status', 'provider_transaction_id', 'needs_attention', 'created_at', 'paid_at',
        ]


class ExtendSerializer(serializers.Serializer):
    user = serializers.IntegerField(required=False, help_text='id пользователя')
    phone = serializers.CharField(required=False)
    plan = serializers.SlugRelatedField(slug_field='code', queryset=Plan.objects.exclude(code=Plan.FREE))
    days = serializers.IntegerField(min_value=1, max_value=366, required=False)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=300)

    def validate(self, attrs):
        users = get_user_model().objects
        user = users.filter(pk=attrs['user']).first() if attrs.get('user') else (
            users.filter(phone=attrs.get('phone', '').strip()).first() if attrs.get('phone') else None
        )
        if user is None:
            raise serializers.ValidationError({'user': 'Пользователь не найден (укажите user или phone).'})
        attrs['user_obj'] = user
        return attrs


class MetricsSerializer(serializers.Serializer):
    paying_total = serializers.IntegerField()
    paying_by_plan = serializers.DictField(child=serializers.IntegerField())
    mrr = serializers.IntegerField()
    churn = serializers.DictField()
    revenue = serializers.DictField()
    new_paying = serializers.IntegerField()
    expiring_7d = serializers.IntegerField()


class AdminSubscriptionListView(generics.ListAPIView):
    """GET /admin-api/billing/subscriptions/?plan=&state=active|expired&q=<телефон>"""
    permission_classes = [permissions.IsAdminUser]
    serializer_class = AdminSubscriptionSerializer

    def get_queryset(self):
        now = timezone.now()
        qs = Subscription.objects.select_related('user', 'plan').annotate(
            paid_total=Coalesce(
                Sum('user__billing_orders__amount', filter=Q(
                    user__billing_orders__status=BillingOrder.STATUS_PAID,
                    user__billing_orders__kind=BillingOrder.KIND_PLAN,
                ) & ~Q(user__billing_orders__provider=BillingOrder.PROVIDER_STUB)),
                Value(0), output_field=DecimalField(max_digits=14, decimal_places=0),
            ),
        ).order_by('ends_at')
        params = self.request.query_params
        if params.get('plan'):
            qs = qs.filter(plan__code=params['plan'])
        if params.get('state') == 'active':
            qs = qs.filter(ends_at__gt=now)
        elif params.get('state') == 'expired':
            qs = qs.filter(ends_at__lte=now)
        if params.get('q'):
            qs = qs.filter(user__phone__icontains=params['q'])
        return qs


class AdminOrderListView(generics.ListAPIView):
    """GET /admin-api/billing/orders/?status=&kind=&provider=&needs_attention=1&q=<телефон>"""
    permission_classes = [permissions.IsAdminUser]
    serializer_class = AdminOrderSerializer

    def get_queryset(self):
        qs = BillingOrder.objects.select_related('user', 'plan')
        params = self.request.query_params
        for name in ('status', 'kind', 'provider'):
            if params.get(name):
                qs = qs.filter(**{name: params[name]})
        if params.get('needs_attention'):
            qs = qs.exclude(needs_attention='')
        if params.get('q'):
            qs = qs.filter(user__phone__icontains=params['q'])
        return qs


class AdminExtendView(APIView):
    """
    POST /admin-api/billing/subscriptions/extend/
    {"user": id | "phone": "...", "plan": "business", "days": 30, "comment": "оплата наличными"}

    Ручное продление: тот же тариф — с конца текущего периода, другой (выше или
    ниже) — сразу. В истории — период с источником «вручную» и автором.
    Снятые по тарифу объявления возвращаются, как после оплаты.
    """
    permission_classes = [permissions.IsAdminUser]

    @extend_schema(request=ExtendSerializer, responses={200: AdminSubscriptionSerializer})
    def post(self, request):
        serializer = ExtendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = data['user_obj']
        subscription = extend_subscription(
            user, data['plan'], days=data.get('days'), source=SubscriptionPeriod.SOURCE_MANUAL,
            created_by=request.user, comment=data.get('comment', ''), replace_active=True,
        )
        restore_paused_listings(user)
        return Response(AdminSubscriptionSerializer(subscription).data, status=status.HTTP_200_OK)


def _paying_at(moment):
    """id пользователей, у которых в момент moment действовал платный период."""
    return set(
        SubscriptionPeriod.objects.filter(starts_at__lte=moment, ends_at__gt=moment)
        .exclude(plan__code=Plan.FREE).exclude(source=SubscriptionPeriod.SOURCE_PROMO)
        .values_list('user_id', flat=True)
    )


class AdminMetricsView(APIView):
    """GET /admin-api/billing/metrics/?days=30 — платящие по тарифам, MRR, отток, выручка."""
    permission_classes = [permissions.IsAdminUser]

    @extend_schema(parameters=[OpenApiParameter('days', int)], responses=MetricsSerializer)
    def get(self, request):
        now = timezone.now()
        try:
            days = max(1, min(int(request.query_params.get('days', 30)), 365))
        except ValueError:
            days = 30
        since = now - timedelta(days=days)

        from .promo import promo_user_ids

        # Тариф по акции — подарок, не платящий.
        active = (Subscription.objects.filter(ends_at__gt=now).exclude(plan__code=Plan.FREE)
                  .exclude(user_id__in=promo_user_ids(now)))
        by_plan = {code: 0 for code in (Plan.START, Plan.BUSINESS, Plan.PRO)}
        mrr = 0
        for code, price, count in active.values_list('plan__code', 'plan__price').annotate(n=Count('pk')):
            by_plan[code] = count
            mrr += int(price) * count

        then, current = _paying_at(since), _paying_at(now)
        churned = len(then - current)
        paid_orders = BillingOrder.objects.filter(
            status=BillingOrder.STATUS_PAID, paid_at__gte=since,
        ).exclude(provider=BillingOrder.PROVIDER_STUB)
        revenue = paid_orders.values('kind').annotate(total=Sum('amount'))
        revenue_by_kind = {row['kind']: int(row['total']) for row in revenue}
        first_paid = (
            SubscriptionPeriod.objects.exclude(plan__code=Plan.FREE).exclude(source=SubscriptionPeriod.SOURCE_PROMO)
            .values('user_id').annotate(first=Min('starts_at')).filter(first__gte=since).count()
        )
        return Response(MetricsSerializer({
            'paying_total': sum(by_plan.values()),
            'paying_by_plan': by_plan,
            'mrr': mrr,
            'churn': {
                'days': days,
                'paying_at_start': len(then),
                'churned': churned,
                'rate': round(churned / len(then), 4) if then else 0.0,
            },
            'revenue': {
                'days': days,
                'total': sum(revenue_by_kind.values()),
                'plans': revenue_by_kind.get(BillingOrder.KIND_PLAN, 0),
                'promotions': revenue_by_kind.get(BillingOrder.KIND_PROMOTION, 0),
            },
            'new_paying': first_paid,
            'expiring_7d': active.filter(ends_at__lte=now + timedelta(days=7)).count(),
        }).data)


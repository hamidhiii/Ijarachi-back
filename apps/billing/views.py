import logging

from django.db import transaction
from django.http import Http404, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.runtime_modes import payments_live, payments_stub_active

from . import checkout, click, payme
from .models import BillingOrder, Plan
from .plans import active_subscription, current_plan
from .serializers import (
    OrderCreatedSerializer,
    OrderCreateSerializer,
    OrderSerializer,
    PlanSerializer,
    PromotionOfferSerializer,
    SubscriptionStateSerializer,
    days_left,
)
from .services import mark_order_paid

logger = logging.getLogger('apps.billing')


class PlanListView(generics.ListAPIView):
    """GET /api/v1/billing/plans/ — тарифы в продаже (FREE тоже — для сравнения)."""
    permission_classes = [permissions.AllowAny]
    serializer_class = PlanSerializer
    pagination_class = None
    queryset = Plan.objects.filter(is_active=True)


class PromotionListView(APIView):
    """GET /api/v1/billing/promotions/ — виды продвижения: цена и срок."""
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=PromotionOfferSerializer(many=True))
    def get(self, request):
        from .promotions import promotion_offers

        return Response(PromotionOfferSerializer(promotion_offers(), many=True).data)


class SubscriptionView(APIView):
    """GET /api/v1/billing/subscription/ — текущий тариф, срок, лимит и занятость."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=SubscriptionStateSerializer)
    def get(self, request):
        from apps.catalog.limits import live_listing_count
        from apps.catalog.models import Item

        subscription = active_subscription(request.user)
        plan = current_plan(request.user)
        ends_at = subscription.ends_at if subscription else None
        data = {
            'plan': PlanSerializer(plan).data,
            'is_paid': plan.is_paid,
            'ends_at': ends_at,
            'days_left': days_left(ends_at),
            'listing_limit': plan.listing_limit,
            'live_listings': live_listing_count(request.user),
            'paused_listings': Item.objects.filter(owner=request.user, status=Item.STATUS_INACTIVE)
            .exclude(plan_paused_status='').count(),
        }
        return Response(SubscriptionStateSerializer(data).data)


class OrderListCreateView(APIView):
    """
    GET  /api/v1/billing/orders/ — мои заказы.
    POST /api/v1/billing/orders/ — оплатить месяц тарифа или продвижение.

    Ответ 201 содержит `redirect_url` — страницу оплаты Click/Payme. При
    PAYMENTS_MODE=stub (dev/staging) заказ сразу оплачен, ссылка ведёт на
    страницу возврата. При PAYMENTS_MODE=off — 503 `PAYMENT_METHOD_UNAVAILABLE`.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'payments'

    @extend_schema(responses=OrderSerializer(many=True))
    def get(self, request):
        orders = BillingOrder.objects.filter(user=request.user).select_related('plan', 'item')[:100]
        return Response(OrderSerializer(orders, many=True).data)

    @extend_schema(request=OrderCreateSerializer, responses={201: OrderCreatedSerializer})
    def post(self, request):
        serializer = OrderCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not (payments_live() or payments_stub_active()):
            return Response(
                {'code': 'PAYMENT_METHOD_UNAVAILABLE', 'detail': 'Онлайн-оплата временно недоступна.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        with transaction.atomic():
            order = BillingOrder.objects.create(
                user=request.user, kind=data['kind'], plan=data.get('plan'),
                promotion=data.get('promotion', ''), item=data.get('item'),
                amount=data['amount'], provider=data['provider'],
            )
        if payments_live():
            redirect_url = (checkout.click_url if order.provider == BillingOrder.PROVIDER_CLICK else checkout.payme_url)(order)
        else:
            order = mark_order_paid(order.pk, provider=BillingOrder.PROVIDER_STUB)
            redirect_url = checkout.return_url(order)
        order.refresh_from_db()
        return Response(
            OrderCreatedSerializer(order, context={'redirect_url': redirect_url}).data,
            status=status.HTTP_201_CREATED,
        )


class OrderDetailView(generics.RetrieveAPIView):
    """GET /api/v1/billing/orders/{id}/ — статус заказа (страница возврата после оплаты)."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OrderSerializer

    def get_queryset(self):
        return BillingOrder.objects.filter(user=self.request.user).select_related('plan', 'item')


# ─── Вебхуки провайдеров (только PAYMENTS_MODE=live) ─────────────────────────

class _LiveOnly(View):
    def dispatch(self, request, *args, **kwargs):
        if not payments_live():
            raise Http404
        return super().dispatch(request, *args, **kwargs)


@method_decorator(csrf_exempt, name='dispatch')
class PaymeWebhookView(_LiveOnly):
    """POST /api/v1/billing/payme/ — Payme Merchant API. Ответ всегда HTTP 200."""

    def post(self, request):
        import json

        if not payme.authorized(request.META.get('HTTP_AUTHORIZATION', '')):
            body_id = None
            try:
                body_id = json.loads(request.body).get('id')
            except Exception:
                pass
            return JsonResponse({'jsonrpc': '2.0', 'id': body_id, 'error': payme.PaymeError(payme.ERR_AUTH).as_dict()})
        try:
            body = json.loads(request.body)
        except ValueError:
            return JsonResponse({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}})
        logger.info('Payme billing: %s', body.get('method') if isinstance(body, dict) else body)
        return JsonResponse(payme.handle(body))


@method_decorator(csrf_exempt, name='dispatch')
class ClickWebhookView(_LiveOnly):
    """POST /api/v1/billing/click/prepare/ и /complete/ — Click SHOP API (form-urlencoded)."""

    def post(self, request):
        data = request.POST if request.POST else _json_or_empty(request)
        logger.info('Click billing: action=%s order=%s', data.get('action'), data.get('merchant_trans_id'))
        return JsonResponse(click.handle(data))


def _json_or_empty(request):
    import json

    try:
        body = json.loads(request.body or b'{}')
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}

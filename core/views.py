import csv

from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from datetime import timedelta
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.serializers import BookingListSerializer
from core.schema import DetailSerializer

# Сколько последних записей отдавать в списках дашборда (не полная выгрузка).
DASHBOARD_LIST_LIMIT = 50


class DashboardStatSerializer(serializers.Serializer):
    label = serializers.CharField()
    value = serializers.CharField()
    delta = serializers.CharField(allow_null=True)


class DashboardUserRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    phone = serializers.CharField()
    verified = serializers.BooleanField()
    status = serializers.ChoiceField(choices=['active', 'blocked'])


class DashboardDisputeRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    deal_id = serializers.IntegerField()
    title = serializers.CharField()
    status = serializers.CharField(help_text='Пока всегда "review" — отдельного ресурса споров нет.')
    amount = serializers.DecimalField(max_digits=12, decimal_places=0)
    created_at = serializers.DateTimeField()


class AdminDashboardResponseSerializer(serializers.Serializer):
    """Ответ GET /admin-api/dashboard/."""
    stats = DashboardStatSerializer(many=True)
    users = DashboardUserRowSerializer(many=True, help_text=f'Последние {DASHBOARD_LIST_LIMIT} по дате регистрации.')
    deals = BookingListSerializer(many=True, help_text=f'Последние {DASHBOARD_LIST_LIMIT} по дате создания.')
    disputes = DashboardDisputeRowSerializer(many=True, help_text=f'Сделки в статусе disputed, последние {DASHBOARD_LIST_LIMIT}.')


@extend_schema(
    responses={200: AdminDashboardResponseSerializer},
    summary='Сводка для админ-консоли',
    description='Только для is_staff. Карточки статистики + короткие списки (не полная выгрузка, см. лимиты в help_text полей).',
)
class AdminDashboardView(APIView):
    """
    GET /api/v1/admin-api/dashboard/
    Формат ответа — карточки статистики + списки для админ-консоли фронта:
    {stats:[{label,value,delta}], users:[...], deals:[...Deal], disputes:[...]}
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.bookings.models import Booking
        from apps.payments.models import Payment
        from apps.users.models import CustomUser

        now = timezone.now()
        month_ago = now - timedelta(days=30)

        paid_payments = Payment.objects.filter(status__in=[Payment.STATUS_PAID, Payment.STATUS_COMPLETED])
        gmv = paid_payments.aggregate(total=Sum('amount'))['total'] or 0

        total_users = CustomUser.objects.count()
        new_users = CustomUser.objects.filter(date_joined__gte=month_ago).count()
        active_deals = Booking.objects.filter(
            status__in=[Booking.STATUS_PAID, Booking.STATUS_IN_PROGRESS, Booking.STATUS_RETURNED]
        ).count()
        disputed_qs = Booking.objects.filter(status=Booking.STATUS_DISPUTED).select_related(
            'item__owner', 'renter'
        ).prefetch_related('item__images').order_by('-updated_at')

        stats = [
            {'label': 'Пользователи', 'value': str(total_users), 'delta': f'+{new_users} за 30 дней'},
            {'label': 'Активные сделки', 'value': str(active_deals), 'delta': None},
            {'label': 'Споры', 'value': str(disputed_qs.count()), 'delta': None},
            {'label': 'GMV (сум)', 'value': str(gmv), 'delta': None},
        ]

        users = [
            {
                'id': user.id,
                'name': getattr(getattr(user, 'profile', None), 'full_name', '') or user.phone,
                'phone': user.phone,
                'verified': bool(getattr(getattr(user, 'profile', None), 'is_verified_kyc', False)),
                'status': 'active' if user.is_active else 'blocked',
            }
            for user in CustomUser.objects.select_related('profile').order_by('-date_joined')[:DASHBOARD_LIST_LIMIT]
        ]

        deals_qs = (
            Booking.objects.select_related('item__owner', 'renter')
            .prefetch_related('item__images', 'photos')
            .order_by('-created_at')[:DASHBOARD_LIST_LIMIT]
        )
        deals = BookingListSerializer(deals_qs, many=True, context={'request': request}).data

        disputes = [
            {
                'id': booking.id,
                'deal_id': booking.id,
                'title': booking.item.title,
                # Отдельной модели споров/статусов рассмотрения пока нет — все
                # сделки в статусе disputed считаются открытыми на рассмотрении.
                'status': 'review',
                'amount': booking.total_price,
                'created_at': booking.created_at,
            }
            for booking in disputed_qs[:DASHBOARD_LIST_LIMIT]
        ]

        return Response({
            'stats': stats,
            'users': users,
            'deals': deals,
            'disputes': disputes,
        })


class AdminUserStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['active', 'blocked'])


@extend_schema(
    request=AdminUserStatusSerializer,
    responses={200: DashboardUserRowSerializer, 400: DetailSerializer, 404: DetailSerializer},
    summary='Заблокировать/разблокировать пользователя',
    description=(
        'Тело: {"status": "active" | "blocked"}. Переключает CustomUser.is_active — '
        'заблокированный пользователь не может авторизоваться (OTP-логин отклоняется), '
        'уже выданные токены не отзываются отдельно. Только для is_staff; заблокировать '
        'самого себя нельзя (400).'
    ),
)
class AdminUserBlockView(APIView):
    permission_classes = [IsAdminUser]

    def patch(self, request, pk):
        from apps.users.models import CustomUser

        if int(pk) == request.user.pk:
            return Response(
                {'detail': 'Нельзя заблокировать собственный аккаунт.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            user = CustomUser.objects.select_related('profile').get(pk=pk)
        except CustomUser.DoesNotExist:
            return Response({'detail': 'Пользователь не найден.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = AdminUserStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user.is_active = serializer.validated_data['status'] == 'active'
        user.save(update_fields=['is_active'])

        return Response({
            'id': user.id,
            'name': getattr(getattr(user, 'profile', None), 'full_name', '') or user.phone,
            'phone': user.phone,
            'verified': bool(getattr(getattr(user, 'profile', None), 'is_verified_kyc', False)),
            'status': 'active' if user.is_active else 'blocked',
        })


@extend_schema(
    responses={200: OpenApiTypes.BINARY},
    summary='Экспорт транзакций в CSV',
    description=(
        'Content-Type: text/csv, Content-Disposition: attachment. Не JSON. '
        'Колонки: id, type, user_phone, deal_id, amount, currency, created_at. '
        'Полная выгрузка Transaction без пагинации и лимита.'
    ),
)
class AdminFinanceExportView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.payments.models import Transaction

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="rentoo-finance-export.csv"'

        writer = csv.writer(response)
        writer.writerow(['id', 'type', 'user_phone', 'deal_id', 'amount', 'currency', 'created_at'])
        qs = Transaction.objects.select_related('user', 'booking').order_by('-created_at')
        for tx in qs:
            writer.writerow([
                tx.id,
                tx.type,
                tx.user.phone if tx.user_id else '',
                tx.booking_id or '',
                tx.amount,
                tx.currency,
                tx.created_at.isoformat(),
            ])

        return response

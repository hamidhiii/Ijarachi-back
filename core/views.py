import csv

from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from datetime import timedelta
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

# Сколько последних записей отдавать в списках дашборда (не полная выгрузка).
DASHBOARD_LIST_LIMIT = 50


class AdminDashboardView(APIView):
    """
    GET /api/v1/admin-api/dashboard/
    Формат ответа — карточки статистики + списки для админ-консоли фронта:
    {stats:[{label,value,delta}], users:[...], deals:[...Deal], disputes:[...]}
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.bookings.models import Booking
        from apps.bookings.serializers import BookingListSerializer
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
            .prefetch_related('item__images')
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

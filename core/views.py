import csv

from django.db.models import Count, Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView


class AdminDashboardView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        from apps.bookings.models import Booking
        from apps.catalog.models import Item
        from apps.payments.models import Payment
        from apps.users.models import CustomUser

        paid_payments = Payment.objects.filter(status__in=[Payment.STATUS_PAID, Payment.STATUS_COMPLETED])
        gmv = paid_payments.aggregate(total=Sum('amount'))['total'] or 0
        active_deals = Booking.objects.filter(
            status__in=[Booking.STATUS_PAID, Booking.STATUS_IN_PROGRESS, Booking.STATUS_RETURNED]
        ).count()

        return Response({
            'generated_at': timezone.now(),
            'users': {
                'total': CustomUser.objects.count(),
                'verified_kyc': CustomUser.objects.filter(profile__is_verified_kyc=True).count(),
            },
            'listings': dict(
                Item.objects.values('status').annotate(count=Count('id')).values_list('status', 'count')
            ),
            'deals': {
                'active': active_deals,
                'disputed': Booking.objects.filter(status=Booking.STATUS_DISPUTED).count(),
                'completed': Booking.objects.filter(status=Booking.STATUS_COMPLETED).count(),
            },
            'finance': {
                'gmv_tiyin': gmv,
                'paid_payments': paid_payments.count(),
            },
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

import logging

from django.db import transaction
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Booking
from .serializers import (
    AssignDelivererSerializer,
    BookingCreateSerializer,
    BookingDetailSerializer,
    BookingListSerializer,
    BookingStatusUpdateSerializer,
    DealPaySerializer,
    DeliveryCalculationSerializer,
    DisputeSerializer,
)
from apps.catalog.models import ItemAvailability

logger = logging.getLogger('apps.bookings')


def user_is_myid_verified(user) -> bool:
    try:
        return bool(user.profile.is_verified_myid)
    except Exception:
        return False


def verification_required_response():
    return Response(
        {
            'code': 'VERIFICATION_REQUIRED',
            'detail': 'Перед созданием сделки нужно пройти MyID verification.',
        },
        status=status.HTTP_403_FORBIDDEN,
    )


class DealCreateView(generics.ListCreateAPIView):
    """
    POST /api/v1/deals/
    Creates a draft deal. Dates are locked when payment is started.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BookingCreateSerializer

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return BookingListSerializer
        return BookingCreateSerializer

    def get_queryset(self):
        return Booking.objects.filter(renter=self.request.user).select_related('item', 'renter', 'deliverer')

    def create(self, request, *args, **kwargs):
        if not user_is_myid_verified(request.user):
            return verification_required_response()
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        deal = serializer.save()
        logger.info('Deal #%s draft created: item=%s renter=%s', deal.pk, deal.item_id, request.user.phone)
        return Response(BookingDetailSerializer(deal, context={'request': request}).data, status=status.HTTP_201_CREATED)


class BookingCreateView(generics.CreateAPIView):
    """
    Legacy POST /api/v1/bookings/create/.
    Creates a payment-pending deal and locks dates immediately.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BookingCreateSerializer

    def create(self, request, *args, **kwargs):
        if not user_is_myid_verified(request.user):
            return verification_required_response()

        serializer = self.get_serializer(
            data=request.data,
            context={'request': request, 'initial_status': Booking.STATUS_PENDING_PAYMENT},
        )
        serializer.is_valid(raise_exception=True)

        item = serializer.validated_data['item']
        start = serializer.validated_data['start_date']
        end = serializer.validated_data['end_date']

        with transaction.atomic():
            avail, _ = ItemAvailability.objects.select_for_update().get_or_create(item=item)
            if not avail.is_available(start, end):
                return Response(
                    {'detail': 'Выбранные даты уже заняты. Попробуйте другие.'},
                    status=status.HTTP_409_CONFLICT,
                )
            booking = serializer.save()
            avail.block_range(start, end)

        logger.info(
            'Booking #%s created: item=%s renter=%s dates=%s to %s total=%s',
            booking.pk, item.pk, request.user.phone, start, end, booking.total_price,
        )
        return Response(BookingDetailSerializer(booking, context={'request': request}).data, status=status.HTTP_201_CREATED)


class MyDealsView(generics.ListAPIView):
    """
    GET /api/v1/deals/?role=renter|owner
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BookingListSerializer

    def get_queryset(self):
        role = self.request.query_params.get('role', 'renter')
        qs = Booking.objects.select_related('item', 'renter', 'deliverer').prefetch_related('item__images')
        if role == 'owner':
            return qs.filter(item__owner=self.request.user)
        return qs.filter(renter=self.request.user)


class MyRentalsView(MyDealsView):
    """
    Backward compatible GET /api/v1/my-rentals/.
    """


class DealDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/deals/{id}/
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BookingDetailSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Booking.objects.select_related('item__owner', 'renter', 'deliverer')
        return qs.filter(renter=user) | qs.filter(item__owner=user)


class BookingDetailView(DealDetailView):
    """
    Backward compatible GET /api/v1/bookings/{id}/.
    """


class DealPayView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'payments'

    def post(self, request, pk):
        if not user_is_myid_verified(request.user):
            return verification_required_response()

        serializer = DealPaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = serializer.validated_data['provider']

        with transaction.atomic():
            try:
                deal = Booking.objects.select_for_update().select_related('item', 'renter').get(pk=pk, renter=request.user)
            except Booking.DoesNotExist:
                return Response({'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

            if deal.status not in [Booking.STATUS_DRAFT, Booking.STATUS_PENDING_PAYMENT]:
                return Response({'detail': f'Нельзя оплатить сделку в статусе {deal.status}.'}, status=status.HTTP_400_BAD_REQUEST)

            avail, _ = ItemAvailability.objects.select_for_update().get_or_create(item=deal.item)
            if not avail.is_available(deal.start_date, deal.end_date):
                return Response({'detail': 'Выбранные даты уже заняты.'}, status=status.HTTP_409_CONFLICT)

            avail.block_range(deal.start_date, deal.end_date)
            deal.status = Booking.STATUS_PENDING_PAYMENT
            deal.escrow_status = Booking.ESCROW_PENDING
            deal.save(update_fields=['status', 'escrow_status', 'updated_at'])

            from apps.payments.models import Payment

            payment = Payment.objects.create(
                booking=deal,
                provider=provider,
                amount=deal.total_price * 100,
                status=Payment.STATUS_PENDING,
                payment_url=f'rentoo://pay/{provider}?deal_id={deal.pk}',
            )
            payment.payment_url = f'rentoo://pay/{provider}?deal_id={deal.pk}&payment_id={payment.pk}'
            payment.save(update_fields=['payment_url'])

        from apps.users.tasks import charge_myid_first_deal_cost
        charge_myid_first_deal_cost.delay(request.user.pk, deal.pk)

        return Response({
            'deal_id': deal.pk,
            'payment_id': payment.pk,
            'provider': payment.provider,
            'amount': payment.amount,
            'payment_url': payment.payment_url,
        }, status=status.HTTP_201_CREATED)


class DealCalculateDeliveryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            deal = Booking.objects.select_related('item', 'renter').get(pk=pk, renter=request.user)
        except Booking.DoesNotExist:
            return Response({'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = DeliveryCalculationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from apps.delivery.services import calculate_delivery_quote

        from_lat = serializer.validated_data.get('from_lat') or deal.item.latitude
        from_lng = serializer.validated_data.get('from_lng') or deal.item.longitude
        quote = calculate_delivery_quote(
            from_lat=from_lat,
            from_lng=from_lng,
            to_lat=serializer.validated_data['to_lat'],
            to_lng=serializer.validated_data['to_lng'],
        )

        deal.delivery_method = Booking.DELIVERY_DELIVERY
        deal.delivery_cost = quote['cost']
        deal.delivery_lat = serializer.validated_data['to_lat']
        deal.delivery_lng = serializer.validated_data['to_lng']
        deal.total_price = deal.price_per_day * deal.days + deal.commission_amount + deal.deposit_amount + deal.delivery_cost
        deal.escrow_amount = deal.total_price
        deal.save(update_fields=[
            'delivery_method',
            'delivery_cost',
            'delivery_lat',
            'delivery_lng',
            'total_price',
            'escrow_amount',
            'updated_at',
        ])
        return Response({'deal': BookingDetailSerializer(deal, context={'request': request}).data, 'delivery': quote})


class ConfirmReturnView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            deal = Booking.objects.select_related('item__owner', 'renter').get(pk=pk, renter=request.user)
        except Booking.DoesNotExist:
            return Response({'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

        if deal.status != Booking.STATUS_IN_PROGRESS:
            return Response({'detail': 'Возврат можно подтвердить только для активной сделки.'}, status=status.HTTP_400_BAD_REQUEST)

        deal.status = Booking.STATUS_RETURNED
        deal.returned_at = timezone.now()
        deal.save(update_fields=['status', 'returned_at', 'updated_at'])
        return Response(BookingDetailSerializer(deal, context={'request': request}).data)


class DisputeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        serializer = DisputeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            deal = Booking.objects.select_related('item__owner', 'renter').get(pk=pk)
        except Booking.DoesNotExist:
            return Response({'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

        if request.user not in [deal.renter, deal.item.owner]:
            return Response({'detail': 'Нет доступа к этой сделке.'}, status=status.HTTP_403_FORBIDDEN)
        if deal.status not in [Booking.STATUS_PAID, Booking.STATUS_IN_PROGRESS, Booking.STATUS_RETURNED]:
            return Response({'detail': 'Спор нельзя открыть в текущем статусе.'}, status=status.HTTP_400_BAD_REQUEST)

        deal.status = Booking.STATUS_DISPUTED
        deal.escrow_status = Booking.ESCROW_FROZEN
        deal.dispute_reason = serializer.validated_data['reason']
        deal.save(update_fields=['status', 'escrow_status', 'dispute_reason', 'updated_at'])
        return Response(BookingDetailSerializer(deal, context={'request': request}).data)


class BookingStatusUpdateView(APIView):
    """
    PATCH /api/v1/deals/{id}/status/ and legacy /bookings/{id}/status/.
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        try:
            booking = Booking.objects.select_related('item__owner', 'renter', 'deliverer').get(pk=pk)
        except Booking.DoesNotExist:
            return Response({'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = BookingStatusUpdateSerializer(
            data=request.data,
            context={'booking': booking, 'request': request},
        )
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']

        with transaction.atomic():
            booking.transition_to(new_status)

            if new_status == Booking.STATUS_CANCELLED:
                self._handle_cancellation(booking)
            elif new_status == Booking.STATUS_DISPUTED:
                booking.escrow_status = Booking.ESCROW_FROZEN
                booking.save(update_fields=['escrow_status', 'updated_at'])
            elif new_status == Booking.STATUS_RETURNED:
                booking.returned_at = timezone.now()
                booking.save(update_fields=['returned_at', 'updated_at'])
            elif new_status == Booking.STATUS_COMPLETED:
                from apps.bookings.tasks import release_escrow
                release_escrow.delay(booking.pk)

        return Response(BookingDetailSerializer(booking, context={'request': request}).data)

    def _handle_cancellation(self, booking):
        try:
            avail = ItemAvailability.objects.select_for_update().get(item=booking.item)
            avail.unblock_range(booking.start_date, booking.end_date)
        except ItemAvailability.DoesNotExist:
            pass

        from apps.payments.models import Payment, Transaction

        paid_payments = list(booking.payments.filter(status=Payment.STATUS_PAID))
        booking.payments.filter(status=Payment.STATUS_PAID).update(status=Payment.STATUS_REFUNDED)
        for payment in paid_payments:
            Transaction.objects.create(
                booking=booking,
                payment=payment,
                user=booking.renter,
                type=Transaction.TYPE_REFUND,
                amount=booking.total_price,
                currency='UZS',
                metadata={'source': 'deal_cancelled'},
            )
        booking.escrow_status = Booking.ESCROW_REFUNDED
        booking.save(update_fields=['escrow_status', 'updated_at'])
        logger.info('Booking #%s cancelled - payment refunded', booking.pk)


class AssignDelivererView(APIView):
    """
    Legacy admin endpoint for assigning an internal deliverer.
    """
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        try:
            booking = Booking.objects.select_related('item__owner', 'renter').get(pk=pk)
        except Booking.DoesNotExist:
            return Response({'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

        if booking.status != Booking.STATUS_PAID:
            return Response(
                {'detail': f'Назначить доставщика можно только для статуса "paid", текущий: "{booking.status}".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = AssignDelivererSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        deliverer = serializer.validated_data['deliverer_id']

        with transaction.atomic():
            booking.deliverer = deliverer
            booking.pickup_eta = serializer.validated_data['pickup_eta']
            booking.delivery_eta = serializer.validated_data['delivery_eta']
            booking.save(update_fields=['deliverer', 'pickup_eta', 'delivery_eta', 'updated_at'])
            booking.transition_to(Booking.STATUS_IN_PROGRESS)

        logger.info('Booking #%s -> in_progress, deliverer=%s', booking.pk, deliverer)
        return Response(BookingDetailSerializer(booking, context={'request': request}).data)

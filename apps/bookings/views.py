import logging
from django.db import transaction
from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Booking
from .serializers import (
    BookingCreateSerializer,
    BookingListSerializer,
    BookingDetailSerializer,
    BookingStatusUpdateSerializer,
    AssignDelivererSerializer,
)
from apps.catalog.models import ItemAvailability

logger = logging.getLogger('apps.bookings')


class BookingCreateView(generics.CreateAPIView):
    """
    POST /api/v1/bookings/create/
    Создание бронирования. Деньги замораживаются через Payme/Click.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BookingCreateSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
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
            'Booking #%s created: item=%s renter=%s dates=%s→%s total=%s',
            booking.pk, item.pk, request.user.phone, start, end, booking.total_price,
        )

        return Response(
            BookingDetailSerializer(booking, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class MyRentalsView(generics.ListAPIView):
    """
    GET /api/v1/my-rentals/?role=renter|owner
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BookingListSerializer

    def get_queryset(self):
        role = self.request.query_params.get('role', 'renter')
        qs = (
            Booking.objects
            .select_related('item', 'renter', 'deliverer')
            .prefetch_related('item__images')
        )
        if role == 'owner':
            return qs.filter(item__owner=self.request.user)
        return qs.filter(renter=self.request.user)


class BookingDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/bookings/{id}/
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BookingDetailSerializer

    def get_queryset(self):
        user = self.request.user
        return (
            Booking.objects.filter(renter=user) |
            Booking.objects.filter(item__owner=user)
        ).select_related('item__owner', 'renter', 'deliverer')


class BookingStatusUpdateView(APIView):
    """
    PATCH /api/v1/bookings/{id}/status/
    Смена статуса в зависимости от роли.
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        try:
            booking = Booking.objects.select_related('item__owner', 'renter', 'deliverer').get(pk=pk)
        except Booking.DoesNotExist:
            return Response({'detail': 'Бронирование не найдено.'}, status=status.HTTP_404_NOT_FOUND)

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

            if new_status == Booking.STATUS_COMPLETED:
                from apps.bookings.tasks import release_escrow
                release_escrow.delay(booking.pk)

        return Response(BookingDetailSerializer(booking, context={'request': request}).data)

    def _handle_cancellation(self, booking):
        # Unblock dates
        try:
            avail = ItemAvailability.objects.select_for_update().get(item=booking.item)
            avail.unblock_range(booking.start_date, booking.end_date)
        except ItemAvailability.DoesNotExist:
            pass

        # Mark payment as refunded
        from apps.payments.models import Payment
        booking.payments.filter(status=Payment.STATUS_PAID).update(status=Payment.STATUS_REFUNDED)
        logger.info('Booking #%s cancelled — payment refunded', booking.pk)


class AssignDelivererView(APIView):
    """
    POST /api/v1/bookings/{id}/assign-deliverer/
    Admin-only: assign deliverer and set ETAs.
    Transitions booking from placed → pickup_scheduled.
    """
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        try:
            booking = Booking.objects.select_related('item__owner', 'renter').get(pk=pk)
        except Booking.DoesNotExist:
            return Response({'detail': 'Бронирование не найдено.'}, status=status.HTTP_404_NOT_FOUND)

        if booking.status != Booking.STATUS_PLACED:
            return Response(
                {'detail': f'Назначить доставщика можно только для статуса "placed", текущий: "{booking.status}".'},
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
            booking.transition_to(Booking.STATUS_PICKUP_SCHEDULED)

        logger.info(
            'Booking #%s → pickup_scheduled, deliverer=%s pickup_eta=%s delivery_eta=%s',
            booking.pk, deliverer, booking.pickup_eta, booking.delivery_eta,
        )

        return Response(BookingDetailSerializer(booking, context={'request': request}).data)

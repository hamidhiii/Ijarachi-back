import logging
from django.db import transaction
from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser

from .models import Booking, VerificationPhoto
from .serializers import (
    BookingCreateSerializer,
    BookingListSerializer,
    BookingDetailSerializer,
    BookingStatusUpdateSerializer,
    VerificationPhotoUploadSerializer,
    VerificationPhotoSerializer,
)
from apps.catalog.models import ItemAvailability

logger = logging.getLogger('apps.bookings')


class BookingCreateView(generics.CreateAPIView):
    """
    POST /api/v1/bookings/create/
    Создание бронирования с защитой от Race Condition (SELECT FOR UPDATE).
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
            # Lock the availability row to prevent race conditions
            avail, _ = ItemAvailability.objects.select_for_update().get_or_create(item=item)

            if not avail.is_available(start, end):
                return Response(
                    {'detail': 'Выбранные даты уже заняты. Попробуйте другие.'},
                    status=status.HTTP_409_CONFLICT,
                )

            booking = serializer.save()
            # Block dates immediately after booking creation
            avail.block_range(start, end)

        logger.info(
            'Booking #%s created: item=%s renter=%s dates=%s→%s total=%s',
            booking.pk, item.pk, request.user.phone, start, end, booking.total_price
        )

        from apps.bookings.tasks import notify_owner_new_booking
        notify_owner_new_booking.delay(booking.pk)

        return Response(
            BookingDetailSerializer(booking, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class MyRentalsView(generics.ListAPIView):
    """
    GET /api/v1/my-rentals/?role=renter|owner
    Мои сделки — как арендатор или как владелец.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BookingListSerializer

    def get_queryset(self):
        role = self.request.query_params.get('role', 'renter')
        qs = (
            Booking.objects
            .select_related('item', 'renter')
            .prefetch_related('item__images')
        )
        if role == 'owner':
            return qs.filter(item__owner=self.request.user)
        return qs.filter(renter=self.request.user)


class BookingDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/bookings/{id}/
    Детали бронирования (только участники сделки).
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BookingDetailSerializer

    def get_queryset(self):
        user = self.request.user
        return Booking.objects.filter(
            renter=user
        ) | Booking.objects.filter(item__owner=user)


class BookingStatusUpdateView(APIView):
    """
    PATCH /api/v1/bookings/{id}/status/
    Смена статуса сделки (роль-зависимо).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_booking(self, pk, user):
        try:
            return Booking.objects.select_related('item__owner', 'renter').get(pk=pk)
        except Booking.DoesNotExist:
            return None

    def patch(self, request, pk):
        booking = self.get_booking(pk, request.user)
        if not booking:
            return Response({'detail': 'Бронирование не найдено.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = BookingStatusUpdateSerializer(
            data=request.data,
            context={'booking': booking, 'request': request},
        )
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']

        with transaction.atomic():
            booking.transition_to(new_status)

            # If cancelled — unblock dates
            if new_status == Booking.STATUS_CANCELLED:
                try:
                    avail = ItemAvailability.objects.select_for_update().get(item=booking.item)
                    avail.unblock_range(booking.start_date, booking.end_date)
                except ItemAvailability.DoesNotExist:
                    pass

            # If completed — trigger escrow release (async)
            if new_status == Booking.STATUS_COMPLETED:
                from apps.bookings.tasks import release_escrow
                release_escrow.delay(booking.pk)

        return Response(BookingDetailSerializer(booking, context={'request': request}).data)


class VerificationPhotoUploadView(APIView):
    """
    POST /api/v1/bookings/{id}/photos/
    Загрузка фото верификации с метаданными.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_booking(self, pk, user):
        try:
            booking = Booking.objects.select_related('item__owner', 'renter').get(pk=pk)
            if user not in (booking.renter, booking.item.owner):
                return None
            return booking
        except Booking.DoesNotExist:
            return None

    def post(self, request, pk):
        booking = self.get_booking(pk, request.user)
        if not booking:
            return Response({'detail': 'Бронирование не найдено.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = VerificationPhotoUploadSerializer(
            data=request.data,
            context={'booking': booking, 'request': request},
        )
        serializer.is_valid(raise_exception=True)
        photo = serializer.save()
        return Response(VerificationPhotoSerializer(photo, context={'request': request}).data, status=status.HTTP_201_CREATED)

    def get(self, request, pk):
        booking = self.get_booking(pk, request.user)
        if not booking:
            return Response({'detail': 'Бронирование не найдено.'}, status=status.HTTP_404_NOT_FOUND)

        photos = booking.verification_photos.all()
        return Response(VerificationPhotoSerializer(photos, many=True, context={'request': request}).data)

class ComparePhotosAIView(APIView):
    """
    POST /api/v1/bookings/ai-compare/
    Mocked Vision API endpoint.
    Expecting: { "photo1_id": int, "photo2_id": int }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        import random
        photo1_id = request.data.get('photo1_id')
        photo2_id = request.data.get('photo2_id')

        if not photo1_id or not photo2_id:
            return Response({'detail': 'Укажите ID двух фото.'}, status=status.HTTP_400_BAD_REQUEST)

        # In a real scenario, fetch photos from AWS/S3, pass them to OpenAI Vision or AWS Rekognition
        # and get exact match score or defect mapping.

        # For MVP, we mock the damage score
        score = round(random.uniform(0.7, 1.0), 2)
        flagged = score < 0.85

        return Response({
            'photo1_id': photo1_id,
            'photo2_id': photo2_id,
            'damage_score': score,
            'flagged': flagged,
            'message': 'Модель завершила анализ.'
        })

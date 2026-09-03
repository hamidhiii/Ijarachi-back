import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Booking, DealReview
from .serializers import (
    BookingCreateSerializer,
    BookingDetailSerializer,
    BookingListSerializer,
    BookingPhotoSerializer,
    BookingStatusUpdateSerializer,
    DealReviewSerializer,
    DealPaySerializer,
    DisputeSerializer,
    refresh_user_rating,
)
from apps.catalog.models import ItemAvailability
from core.schema import DetailSerializer

logger = logging.getLogger('apps.bookings')

# Какие сделки возвращать: где пользователь арендатор или где он владелец вещи.
ROLE_PARAMETER = OpenApiParameter(
    name='role',
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    default='renter',
    enum=['renter', 'owner'],
    description=(
        'renter — сделки, где пользователь арендатор (значение по умолчанию); '
        'owner — где он владелец вещи. Любое другое значение трактуется как renter.'
    ),
)


def user_is_kyc_verified(user) -> bool:
    try:
        return bool(user.profile.is_verified_kyc)
    except Exception:
        return False


def verification_required_response():
    return Response(
        {
            'code': 'VERIFICATION_REQUIRED',
            'detail': 'Перед созданием сделки нужно пройти проверку личности (KYC).',
        },
        status=status.HTTP_403_FORBIDDEN,
    )


@extend_schema_view(
    get=extend_schema(
        parameters=[ROLE_PARAMETER],
        responses={200: BookingListSerializer(many=True)},
    ),
    post=extend_schema(
        request=BookingCreateSerializer,
        responses={201: BookingDetailSerializer, 403: DetailSerializer},
    ),
)
class DealCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/deals/?role=renter|owner — список сделок пользователя.
    POST /api/v1/deals/ — черновик сделки; даты фиксируются при начале оплаты.
    403 — если не пройден KYC.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BookingCreateSerializer

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return BookingListSerializer
        return BookingCreateSerializer

    def get_queryset(self):
        role = self.request.query_params.get('role', 'renter')
        qs = Booking.objects.select_related('item__owner', 'renter').prefetch_related('item__images', 'photos')
        if role == 'owner':
            return qs.filter(item__owner=self.request.user)
        return qs.filter(renter=self.request.user)

    def create(self, request, *args, **kwargs):
        if not user_is_kyc_verified(request.user):
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
        if not user_is_kyc_verified(request.user):
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


@extend_schema(parameters=[ROLE_PARAMETER], responses={200: BookingListSerializer(many=True)})
class MyDealsView(generics.ListAPIView):
    """
    GET /api/v1/deals/list/?role=renter|owner
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = BookingListSerializer

    def get_queryset(self):
        role = self.request.query_params.get('role', 'renter')
        qs = Booking.objects.select_related('item__owner', 'renter').prefetch_related('item__images', 'photos')
        if role == 'owner':
            return qs.filter(item__owner=self.request.user)
        return qs.filter(renter=self.request.user)


@extend_schema(parameters=[ROLE_PARAMETER], responses={200: BookingListSerializer(many=True)})
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
        qs = Booking.objects.select_related('item__owner', 'renter').prefetch_related('photos', 'item__images')
        return qs.filter(renter=user) | qs.filter(item__owner=user)


class BookingDetailView(DealDetailView):
    """
    Backward compatible GET /api/v1/bookings/{id}/.
    """


class DealPayView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'payments'

    def post(self, request, pk):
        if not user_is_kyc_verified(request.user):
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

            scheme = settings.APP_DEEPLINK_SCHEME
            payment = Payment.objects.create(
                booking=deal,
                provider=provider,
                amount=deal.total_price * 100,
                status=Payment.STATUS_PENDING,
                payment_url=f'{scheme}://pay/{provider}?deal_id={deal.pk}',
            )
            payment.payment_url = f'{scheme}://pay/{provider}?deal_id={deal.pk}&payment_id={payment.pk}'
            payment.save(update_fields=['payment_url'])

        from apps.users.tasks import charge_kyc_first_deal_cost
        charge_kyc_first_deal_cost.delay(request.user.pk, deal.pk)

        return Response({
            'payment_id': payment.pk,
            'provider': payment.provider,
            'redirect_url': payment.payment_url,
            # Доп. поля для обратной совместимости с мобильным клиентом.
            'deal_id': deal.pk,
            'amount': payment.amount,
        }, status=status.HTTP_201_CREATED)


@extend_schema(
    request=None,
    responses={200: BookingDetailSerializer, 400: DetailSerializer, 404: DetailSerializer},
    summary='Арендатор подтверждает возврат',
    description=(
        'Тело не нужно. Переводит сделку из in_progress (active) в returned и ставит '
        'серверный returned_at. Фото при возврате не требуется.\n\n'
        'Вызвать может только арендатор этой сделки: для всех остальных, включая владельца, '
        'сделка просто не находится — 404, не 403. 400 — сделка не в статусе in_progress. '
        'В ответе полная карточка сделки.'
    ),
)
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


@extend_schema(
    request=DealReviewSerializer,
    responses={
        201: DealReviewSerializer,
        400: DetailSerializer,
        403: DetailSerializer,
        404: DetailSerializer,
    },
    summary='Отзыв по сделке',
    description=(
        'Клиент присылает только rating (1-5) и comment. Адресат отзыва (reviewee) и автор '
        '(reviewer) выводятся сервером из сделки: арендатор оценивает владельца и наоборот, '
        'переданные в теле reviewer/reviewee игнорируются.\n\n'
        '403 — вызывающий не арендатор и не владелец сделки. '
        '400 — сделка не в статусе completed/returned либо отзыв уже оставлен. '
        '404 — сделки нет.'
    ),
)
class DealReviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            deal = Booking.objects.select_related('item__owner', 'renter').get(pk=pk)
        except Booking.DoesNotExist:
            return Response({'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

        if request.user not in [deal.renter, deal.item.owner]:
            return Response({'detail': 'Нет доступа к этой сделке.'}, status=status.HTTP_403_FORBIDDEN)
        if deal.status not in [Booking.STATUS_COMPLETED, Booking.STATUS_RETURNED]:
            return Response({'detail': 'Отзыв можно оставить после завершения или подтверждения возврата.'}, status=status.HTTP_400_BAD_REQUEST)
        if deal.reviews.filter(reviewer=request.user).exists():
            return Response({'detail': 'Вы уже оставили отзыв по этой сделке.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = DealReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reviewee = deal.item.owner if request.user == deal.renter else deal.renter
        review = serializer.save(
            booking=deal,
            listing=deal.item,
            reviewer=request.user,
            reviewee=reviewee,
        )
        refresh_user_rating(reviewee)
        return Response(DealReviewSerializer(review, context={'request': request}).data, status=status.HTTP_201_CREATED)


@extend_schema(
    request={'multipart/form-data': BookingPhotoSerializer},
    responses={
        201: BookingPhotoSerializer,
        400: DetailSerializer,
        403: DetailSerializer,
        404: DetailSerializer,
    },
    summary='Загрузка фото по сделке',
    description=(
        'multipart/form-data. Поля: image (файл, обязателен), kind (before | after | issue), '
        'comment (текст, необязателен). booking и uploaded_by проставляет сервер.\n\n'
        '403 — вызывающий не участник сделки либо сделка ещё не оплачена '
        '(разрешены статусы paid, in_progress, returned, completed, disputed). '
        '404 — сделки нет.'
    ),
)
class BookingPhotoUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    ALLOWED_STATUSES = [
        Booking.STATUS_PAID,
        Booking.STATUS_IN_PROGRESS,
        Booking.STATUS_RETURNED,
        Booking.STATUS_COMPLETED,
        Booking.STATUS_DISPUTED,
    ]

    def post(self, request, pk):
        try:
            deal = Booking.objects.select_related('item__owner', 'renter').get(pk=pk)
        except Booking.DoesNotExist:
            return Response({'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

        if request.user not in [deal.renter, deal.item.owner]:
            return Response({'detail': 'Нет доступа к этой сделке.'}, status=status.HTTP_403_FORBIDDEN)
        if deal.status not in self.ALLOWED_STATUSES:
            return Response({'detail': 'Фото можно добавить только после оплаты сделки.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = BookingPhotoSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        photo = serializer.save(booking=deal, uploaded_by=request.user)
        return Response(BookingPhotoSerializer(photo, context={'request': request}).data, status=status.HTTP_201_CREATED)


@extend_schema(
    request=BookingStatusUpdateSerializer,
    responses={200: BookingDetailSerializer, 400: DetailSerializer, 404: DetailSerializer},
    summary='Смена статуса сделки',
    description=(
        'Тело: {"status": "<новый статус>"}. Принимаются и публичные значения '
        '(pending, confirmed, active, returned, completed, cancelled, disputed), и внутренние '
        '(draft, pending_payment, paid, in_progress, ...) — публичные предпочтительны.\n\n'
        'Разрешённые переходы (из статуса + кем):\n'
        '- draft, pending_payment → cancelled: арендатор\n'
        '- paid (confirmed) → in_progress (active): арендатор или владелец\n'
        '- paid (confirmed) → cancelled: арендатор\n'
        '- in_progress (active) → returned: только арендатор\n'
        '- in_progress (active) → disputed: арендатор или владелец\n'
        '- returned → completed: только владелец\n\n'
        'Перехода в paid (confirmed) нет ни у кого: сделка становится оплаченной по вебхуку '
        'провайдера, а не этим эндпоинтом. Сотрудник (is_staff) может поставить любой статус.\n\n'
        'Фото при выдаче для перехода в active не требуется. Любой другой переход, как и вызов '
        'посторонним, отклоняется с 400 и текстом причины в ошибках поля status.'
    ),
)
class BookingStatusUpdateView(APIView):
    """
    PATCH /api/v1/deals/{id}/status/ and legacy /bookings/{id}/status/.
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        try:
            booking = Booking.objects.select_related('item__owner', 'renter').get(pk=pk)
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


# Маршруты /users/{id}/reviews/ и /profile/reviews/ объявлены в этом приложении,
# потому что здесь живёт модель DealReview.

@extend_schema(
    responses={200: DealReviewSerializer(many=True)},
    summary='Отзывы о пользователе',
    description=(
        'Отзывы, где человек — адресат (reviewee), независимо от того, чьё объявление. '
        'id в пути — ключ пользователя: тот же, что /profile/ отдаёт как id и что стоит '
        'в DealReview.reviewee.'
    ),
)
class UserReviewsView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = DealReviewSerializer
    # Пустой queryset нужен, чтобы drf-spectacular видел модель: get_queryset
    # опирается на kwargs и при генерации схемы падал бы.
    queryset = DealReview.objects.none()

    def reviews_for(self, user_id):
        return (
            DealReview.objects
            .filter(reviewee_id=user_id)
            .select_related('reviewer__profile', 'reviewee__profile', 'booking', 'listing')
            .order_by('-created_at')
        )

    def get_queryset(self):
        return self.reviews_for(self.kwargs['pk'])


@extend_schema(
    responses={200: DealReviewSerializer(many=True)},
    summary='Отзывы обо мне',
    description='То же самое для текущего пользователя, без подстановки своего id.',
)
class MyReviewsView(UserReviewsView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.reviews_for(self.request.user.pk)

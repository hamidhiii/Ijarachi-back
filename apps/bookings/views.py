import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics, permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Booking, BookingPhoto, DealReview
from .serializers import (
    BookingCreateSerializer,
    BookingDetailSerializer,
    BookingListSerializer,
    BookingPhotoSerializer,
    BookingStatusUpdateSerializer,
    DealReviewSerializer,
    DealPayResponseSerializer,
    DealPaySerializer,
    DealPreviewResponseSerializer,
    DealPreviewSerializer,
    DisputeSerializer,
    compute_pricing,
    refresh_user_rating,
    require_handover_photo,
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


@extend_schema(
    request=DealPreviewSerializer,
    responses={200: DealPreviewResponseSerializer, 400: DetailSerializer},
    summary='Предпросмотр стоимости сделки',
    description=(
        'Тело: {"item", "start_date", "end_date"}. Тот же расчёт, что при создании '
        'сделки (days, price_per_day, deposit, commission_amount, total_price), но '
        'ничего не создаёт и не проверяет занятость дат — только цена, до отправки '
        'запроса. Доступен без KYC: это витрина, а не бронирование.\n\n'
        '400 — объявления нет/оно не approved (стандартная ошибка поля item), '
        'либо дата начала позже даты конца.'
    ),
)
class DealPreviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = DealPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        pricing = compute_pricing(data['item'], data['start_date'], data['end_date'])
        return Response(DealPreviewResponseSerializer(pricing).data)


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

        from apps.bookings.tasks import notify_owner_new_booking
        notify_owner_new_booking.delay(deal.pk)

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

        from apps.bookings.tasks import notify_owner_new_booking
        notify_owner_new_booking.delay(booking.pk)

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


@extend_schema(
    request=DealPaySerializer,
    responses={
        201: DealPayResponseSerializer,
        400: DetailSerializer,
        403: DetailSerializer,
        404: DetailSerializer,
        409: DetailSerializer,
    },
    summary='Выбрать способ оплаты сделки',
    description=(
        'Тело: {"provider": "payme" | "click" | "cash"}. Блокирует даты в календаре и '
        'переводит сделку в pending_payment.\n\n'
        'payme и click возвращают redirect_url; сделка станет confirmed по вебхуку провайдера.\n'
        'cash — расчёт при получении: redirect_url отсутствует, эскроу неприменим, '
        'из ожидания сделку выводит владелец переходом в confirmed.\n\n'
        '403 — не пройден KYC. 400 — сделку в этом статусе оплатить нельзя. '
        '409 — даты успели занять. 404 — сделки нет либо вызывающий не арендатор.'
    ),
)
class DealPayView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'payments'

    # Дальше по статусу однозначно понятно, почему платить нельзя — фронту нужно
    # различать «уже оплачено» от «сделка закрыта», а не только текст detail.
    ALREADY_PAID_STATUSES = [
        Booking.STATUS_PAID, Booking.STATUS_IN_PROGRESS,
        Booking.STATUS_RETURNED, Booking.STATUS_COMPLETED,
    ]

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
                return Response(
                    {'code': 'DEAL_NOT_FOUND', 'detail': 'Сделка не найдена.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if deal.status not in [Booking.STATUS_DRAFT, Booking.STATUS_PENDING_PAYMENT]:
                if deal.status in self.ALREADY_PAID_STATUSES:
                    code, detail = 'ALREADY_PAID', 'Эта сделка уже оплачена.'
                else:
                    code, detail = 'DEAL_CLOSED', f'Сделка в статусе {deal.public_status} больше не оплачивается.'
                return Response({'code': code, 'detail': detail}, status=status.HTTP_400_BAD_REQUEST)

            avail, _ = ItemAvailability.objects.select_for_update().get_or_create(item=deal.item)
            if not avail.is_available(deal.start_date, deal.end_date):
                return Response(
                    {'code': 'DATES_UNAVAILABLE', 'detail': 'Выбранные даты уже заняты.'},
                    status=status.HTTP_409_CONFLICT,
                )

            avail.block_range(deal.start_date, deal.end_date)
            deal.status = Booking.STATUS_PENDING_PAYMENT
            deal.escrow_status = Booking.ESCROW_PENDING
            deal.save(update_fields=['status', 'escrow_status', 'updated_at'])

            from apps.payments.models import Payment
            from apps.payments.checkout import build_redirect_url

            payment = Payment.objects.create(
                booking=deal,
                provider=provider,
                amount=deal.total_price * 100,
                status=Payment.STATUS_PENDING,
            )
            if provider == Payment.PROVIDER_CASH:
                # Наличными при получении: вести некуда, платформа денег не держит,
                # поэтому эскроу к сделке неприменим с самого начала.
                deal.escrow_status = Booking.ESCROW_NONE
                deal.save(update_fields=['escrow_status', 'updated_at'])
            else:
                payment.payment_url = build_redirect_url(payment)
                payment.save(update_fields=['payment_url'])

        from apps.users.tasks import charge_kyc_first_deal_cost
        charge_kyc_first_deal_cost.delay(request.user.pk, deal.pk)

        return Response({
            'payment_id': payment.pk,
            'provider': payment.provider,
            'status': payment.status,
            'redirect_url': payment.payment_url or None,
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
        'серверный returned_at. Требует хотя бы один снимок kind=after — без него 400.\n\n'
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

        try:
            require_handover_photo(deal, Booking.STATUS_RETURNED)
        except ValidationError as exc:
            return Response({'detail': exc.detail[0] if isinstance(exc.detail, list) else exc.detail},
                            status=status.HTTP_400_BAD_REQUEST)

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
        'comment (текст, необязателен). booking, uploaded_by и время проставляет сервер.\n\n'
        'Каждый вид снимка принимается только в своём окне, иначе 400:\n'
        '- before — только пока сделка в paid (confirmed), то есть до выдачи вещи;\n'
        '- after — с in_progress (active) и далее: returned, disputed;\n'
        '- issue — в любом статусе, где загрузка вообще разрешена.\n\n'
        'Окна нужны, чтобы снимок «при выдаче» нельзя было добавить задним числом, уже после '
        'порчи вещи.\n\n'
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

    # В каком статусе какой снимок имеет смысл. Без этого «фото при выдаче»
    # можно загрузить уже после порчи вещи, и оно перестаёт быть доказательством.
    KIND_WINDOWS = {
        BookingPhoto.KIND_BEFORE: [Booking.STATUS_PAID],
        BookingPhoto.KIND_AFTER: [
            Booking.STATUS_IN_PROGRESS,
            Booking.STATUS_RETURNED,
            Booking.STATUS_DISPUTED,
        ],
        BookingPhoto.KIND_ISSUE: ALLOWED_STATUSES,
    }

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

        kind = serializer.validated_data['kind']
        if deal.status not in self.KIND_WINDOWS.get(kind, []):
            return Response(
                {'detail': f'Снимок «{kind}» нельзя добавить к сделке в статусе "{deal.status}".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
        '- draft, pending_payment → cancelled: арендатор или владелец\n'
        '- pending_payment → paid (confirmed): только владелец — так бронь с расчётом '
        'наличными выходит из ожидания. У payme и click это делает вебхук провайдера, '
        'и вручную такой переход не нужен.\n'
        '- paid (confirmed) → in_progress (active): арендатор или владелец\n'
        '- paid (confirmed) → cancelled: арендатор\n'
        '- in_progress (active) → returned: только арендатор\n'
        '- in_progress (active) → disputed: арендатор или владелец\n'
        '- returned → completed: только владелец\n\n'
        'Фотопротокол обязателен: в active не пустят без снимка kind=before, в returned — '
        'без kind=after (отключается настройкой BOOKING_REQUIRE_HANDOVER_PHOTO). '
        'Сотрудник (is_staff) может поставить любой статус и не связан этими правилами.\n\n'
        'Любой другой переход, как и вызов посторонним, отклоняется с 400 и текстом причины '
        'в ошибках поля status.'
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
            elif new_status == Booking.STATUS_PAID:
                self._confirm_without_provider(booking)
            elif new_status == Booking.STATUS_COMPLETED:
                from apps.bookings.tasks import release_escrow
                release_escrow.delay(booking.pk)

        from apps.bookings.tasks import notify_status_change
        notify_status_change.delay(booking.pk, request.user.pk)

        return Response(BookingDetailSerializer(booking, context={'request': request}).data)

    def _confirm_without_provider(self, booking):
        """
        Владелец принял бронь с расчётом наличными. Денег платформа не получала,
        поэтому эскроу остаётся неприменимым, а платёж — pending: он закроется,
        когда сделка дойдёт до completed. Контакты раскрываем: сторонам встречаться.
        """
        from apps.payments.models import Payment

        if booking.payments.filter(provider=Payment.PROVIDER_CASH).exists():
            booking.escrow_status = Booking.ESCROW_NONE

        if booking.contact_revealed_at is None:
            booking.contact_revealed_at = timezone.now()
        booking.save(update_fields=['escrow_status', 'contact_revealed_at', 'updated_at'])
        logger.info('Booking #%s confirmed by owner without provider payment', booking.pk)

    def _handle_cancellation(self, booking):
        try:
            avail = ItemAvailability.objects.select_for_update().get(item=booking.item)
            avail.unblock_range(booking.start_date, booking.end_date)
        except ItemAvailability.DoesNotExist:
            pass

        from apps.payments.models import Payment, Transaction

        # Наличные платформа не принимала — возвращать нечего, иначе в отчётности
        # появится движение денег, которого не было.
        cash_only = not booking.payments.exclude(provider=Payment.PROVIDER_CASH).exists()
        paid_payments = list(booking.payments.filter(status=Payment.STATUS_PAID).exclude(provider=Payment.PROVIDER_CASH))
        booking.payments.filter(status=Payment.STATUS_PAID).exclude(provider=Payment.PROVIDER_CASH).update(
            status=Payment.STATUS_REFUNDED
        )
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
        booking.escrow_status = Booking.ESCROW_NONE if cash_only else Booking.ESCROW_REFUNDED
        booking.save(update_fields=['escrow_status', 'updated_at'])
        logger.info('Booking #%s cancelled (cash_only=%s)', booking.pk, cash_only)


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

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
from .availability import is_range_free, lock_item
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
    DisputeResolutionSerializer,
    DisputeSerializer,
    PayoutPreviewQuerySerializer,
    PayoutPreviewResponseSerializer,
    compute_pricing,
    payout_preview,
    refresh_user_rating,
    require_handover_photo,
)
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
    if not settings.KYC_ENABLED:
        return True
    try:
        return bool(user.profile.is_verified_kyc)
    except Exception:
        return False


def dates_unavailable_response():
    return Response(
        {'code': 'DATES_UNAVAILABLE', 'detail': 'Выбранные даты уже заняты. Попробуйте другие.'},
        status=status.HTTP_409_CONFLICT,
    )


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
        'сделки, но ничего не создаёт и не проверяет занятость дат. Доступен без KYC.\n\n'
        'Модель B: total_price = аренда + залог; комиссия (commission_amount) удерживается '
        'из выплаты владельцу (owner_payout), сверху не добавляется. Если у вызывающего '
        'есть принятое предложение цены по этому объявлению, price_per_day — согласованная '
        'цена и offer_id указывает на него.\n\n'
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
        pricing = compute_pricing(data['item'], data['start_date'], data['end_date'], renter=request.user)
        return Response(DealPreviewResponseSerializer(pricing).data)


@extend_schema(
    parameters=[PayoutPreviewQuerySerializer],
    responses={200: PayoutPreviewResponseSerializer, 400: DetailSerializer},
    summary='Сколько получит владелец',
    description=(
        '?price_per_day=<сум>&days=<дней, по умолчанию 1>. Комиссия платформы '
        '(PLATFORM_COMMISSION_PERCENT) удерживается из выплаты — для подсказки '
        '«вы получите X» в форме объявления. Без авторизации.'
    ),
)
class PayoutPreviewView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        serializer = PayoutPreviewQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(PayoutPreviewResponseSerializer(payout_preview(data['price_per_day'], data['days'])).data)


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
        data = serializer.validated_data
        with transaction.atomic():
            # Черновик даты не занимает, но заведомо занятые даты не принимает:
            # проверка под той же блокировкой объявления, что и при оплате.
            lock_item(data['item'].pk)
            if not is_range_free(data['item'], data['start_date'], data['end_date']):
                return dates_unavailable_response()
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
            # Бронь сразу в pending_payment — занимает даты с момента создания.
            lock_item(item.pk)
            if not is_range_free(item, start, end):
                return dates_unavailable_response()
            booking = serializer.save()

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
        503: DetailSerializer,
    },
    summary='Выбрать способ оплаты сделки',
    description=(
        'Тело: {"provider": "payme" | "click" | "cash"}. Занимает даты сделки (под '
        'блокировкой объявления) и переводит её в pending_payment. Повторный вызов '
        'для той же сделки разрешён — например, чтобы сменить способ оплаты.\n\n'
        'payme и click зависят от PAYMENTS_MODE: live — redirect_url на чекаут '
        'провайдера, сделка станет confirmed по вебхуку; stub (только dev/staging) — '
        'оплата подтверждается сразу (status=paid, provider=stub), redirect_url ведёт '
        'на страницу сделки; off — 503 PAYMENT_METHOD_UNAVAILABLE.\n'
        'cash — расчёт при получении: redirect_url отсутствует, эскроу и залог через '
        'платформу не идут, из ожидания сделку выводит владелец переходом в confirmed.\n\n'
        '403 — не пройден KYC. 400 — сделку в этом статусе оплатить нельзя. '
        '409 — даты успели занять. 404 — сделки нет либо вызывающий не арендатор. '
        '503 — выбранный способ оплаты выключен.'
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
        provider_code = serializer.validated_data['provider']

        from apps.payments.models import Payment
        from apps.payments.providers import PaymentsUnavailable, get_provider

        try:
            provider = get_provider(provider_code)
        except PaymentsUnavailable as exc:
            return Response(
                {'code': 'PAYMENT_METHOD_UNAVAILABLE', 'detail': str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            with transaction.atomic():
                try:
                    deal = Booking.objects.select_related('item', 'renter').get(pk=pk, renter=request.user)
                except Booking.DoesNotExist:
                    return Response(
                        {'code': 'DEAL_NOT_FOUND', 'detail': 'Сделка не найдена.'},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                # Блокировка объявления разводит две одновременные оплаты одних дат:
                # вторая ждёт, пока первая не займёт даты, и видит их занятыми.
                lock_item(deal.item_id)
                deal = Booking.objects.select_for_update(of=('self',)).select_related('item', 'renter').get(pk=deal.pk)

                if deal.status not in [Booking.STATUS_DRAFT, Booking.STATUS_PENDING_PAYMENT]:
                    if deal.status in self.ALREADY_PAID_STATUSES:
                        code, detail = 'ALREADY_PAID', 'Эта сделка уже оплачена.'
                    else:
                        code, detail = 'DEAL_CLOSED', f'Сделка в статусе {deal.public_status} больше не оплачивается.'
                    return Response({'code': code, 'detail': detail}, status=status.HTTP_400_BAD_REQUEST)

                # Свои же даты сделку не блокируют: повторный вызов (сменить способ
                # оплаты, получить новую ссылку) раньше упирался в 409.
                if not is_range_free(deal.item, deal.start_date, deal.end_date, exclude_booking=deal):
                    return dates_unavailable_response()

                deal.status = Booking.STATUS_PENDING_PAYMENT
                if provider.online:
                    deal.escrow_status = Booking.ESCROW_PENDING
                    deal.deposit_status = Booking.DEPOSIT_PENDING if deal.deposit_amount > 0 else Booking.DEPOSIT_NONE
                else:
                    # Наличными при получении: платформа денег не держит — ни аренду,
                    # ни залог, — поэтому эскроу и залог к сделке неприменимы.
                    deal.escrow_status = Booking.ESCROW_NONE
                    deal.deposit_status = Booking.DEPOSIT_NONE
                deal.save(update_fields=['status', 'escrow_status', 'deposit_status', 'updated_at'])

                # Повторная оплата: прежние незавершённые попытки больше не действуют.
                deal.payments.filter(status=Payment.STATUS_PENDING).update(status=Payment.STATUS_FAILED)
                payment = Payment.objects.create(
                    booking=deal,
                    provider=provider.code,
                    amount=deal.total_price * 100,
                    status=Payment.STATUS_PENDING,
                )
                payment.payment_url = provider.start(payment) or ''
                payment.save(update_fields=['payment_url', 'updated_at'])
                payment.refresh_from_db(fields=['status'])
        except PaymentsUnavailable as exc:
            # Режим оплаты сменился между выбором провайдера и подтверждением —
            # транзакция откатана, сделка осталась как была.
            return Response(
                {'code': 'PAYMENT_METHOD_UNAVAILABLE', 'detail': str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

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
            return Response({'code': 'deal_not_found', 'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

        if deal.status != Booking.STATUS_IN_PROGRESS:
            return Response({'code': 'return_not_allowed', 'detail': 'Возврат можно подтвердить только для активной сделки.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            require_handover_photo(deal, Booking.STATUS_RETURNED)
        except ValidationError as exc:
            return Response(
                {'code': 'handover_photo_required', 'detail': exc.detail[0] if isinstance(exc.detail, list) else exc.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
            return Response({'code': 'deal_not_found', 'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

        if request.user not in [deal.renter, deal.item.owner]:
            return Response({'code': 'deal_access_denied', 'detail': 'Нет доступа к этой сделке.'}, status=status.HTTP_403_FORBIDDEN)
        if deal.status not in [Booking.STATUS_PAID, Booking.STATUS_IN_PROGRESS, Booking.STATUS_RETURNED]:
            return Response({'code': 'dispute_not_allowed', 'detail': 'Спор нельзя открыть в текущем статусе.'}, status=status.HTTP_400_BAD_REQUEST)

        deal.status = Booking.STATUS_DISPUTED
        deal.escrow_status = Booking.ESCROW_FROZEN
        deal.dispute_reason = serializer.validated_data['reason']
        deal.save(update_fields=['status', 'escrow_status', 'dispute_reason', 'updated_at'])
        return Response(BookingDetailSerializer(deal, context={'request': request}).data)


@extend_schema(
    request=DisputeResolutionSerializer,
    responses={200: BookingDetailSerializer, 400: DetailSerializer, 404: DetailSerializer},
    summary='Закрыть спор (сотрудник)',
    description=(
        'Только is_staff. Тело: {"deposit_withheld": <сум>, "comment": "..."}. Сделка '
        'из disputed переходит в completed: аренда (за вычетом комиссии) — владельцу, '
        'deposit_withheld из залога — тоже владельцу, остаток залога — арендатору. '
        'Начисления идут во внутренние кошельки, история — в deposit_operations.\n\n'
        '400 — сделка не в споре либо deposit_withheld больше залога.'
    ),
)
class DisputeResolveView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        from .settlement import SettlementError, resolve_dispute

        if not Booking.objects.filter(pk=pk).exists():
            return Response({'code': 'deal_not_found', 'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = DisputeResolutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            booking = resolve_dispute(
                pk,
                serializer.validated_data['deposit_withheld'],
                actor=request.user,
                comment=serializer.validated_data.get('comment', ''),
            )
        except SettlementError as exc:
            return Response({'code': 'dispute_resolution_invalid', 'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        from apps.bookings.tasks import notify_status_change
        notify_status_change.delay(booking.pk, request.user.pk)
        return Response(BookingDetailSerializer(booking, context={'request': request}).data)


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
            return Response({'code': 'deal_not_found', 'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

        if request.user not in [deal.renter, deal.item.owner]:
            return Response({'code': 'deal_access_denied', 'detail': 'Нет доступа к этой сделке.'}, status=status.HTTP_403_FORBIDDEN)
        if deal.status not in [Booking.STATUS_COMPLETED, Booking.STATUS_RETURNED]:
            return Response({'code': 'review_not_allowed', 'detail': 'Отзыв можно оставить после завершения или подтверждения возврата.'}, status=status.HTTP_400_BAD_REQUEST)
        if deal.reviews.filter(reviewer=request.user).exists():
            return Response({'code': 'review_already_exists', 'detail': 'Вы уже оставили отзыв по этой сделке.'}, status=status.HTTP_400_BAD_REQUEST)

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
            return Response({'code': 'deal_not_found', 'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

        if request.user not in [deal.renter, deal.item.owner]:
            return Response({'code': 'deal_access_denied', 'detail': 'Нет доступа к этой сделке.'}, status=status.HTTP_403_FORBIDDEN)
        if deal.status not in self.ALLOWED_STATUSES:
            return Response({'code': 'deal_not_paid', 'detail': 'Фото можно добавить только после оплаты сделки.'}, status=status.HTTP_403_FORBIDDEN)

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
        '- pending_payment → paid (confirmed): только владелец и только при оплате '
        'наличными (последний выбранный способ — cash). Онлайн-оплату подтверждает '
        'провайдер; попытка владельца подтвердить её вручную — 400.\n'
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
            return Response({'code': 'deal_not_found', 'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

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
                # После коммита: задача должна увидеть сделку уже completed.
                booking_id = booking.pk
                transaction.on_commit(lambda: release_escrow.delay(booking_id))

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
        # Даты освобождать не нужно: их занимает сама бронь, пока она активна,
        # — отмена освобождает ровно её дни и ничьи больше.
        from apps.bookings.settlement import refund_deposit_on_cancel
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
        refund_deposit_on_cancel(booking, 'Сделка отменена', actor=self.request.user)
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

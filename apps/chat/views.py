from django.conf import settings
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.models import Booking
from apps.catalog.models import Item
from core.schema import DetailSerializer
from .models import Conversation, Message
from .serializers import (
    ConversationCreateSerializer,
    ConversationReadResponseSerializer,
    ConversationSerializer,
    MessageSerializer,
)


@extend_schema_view(
    get=extend_schema(
        responses={200: ConversationSerializer(many=True)},
        summary='Диалоги пользователя',
        description='Все диалоги, где вызывающий — участник. Пагинации нет, возвращается полный список.',
    ),
    post=extend_schema(
        request=ConversationCreateSerializer,
        responses={
            201: ConversationSerializer, 200: ConversationSerializer,
            400: DetailSerializer, 403: DetailSerializer, 404: DetailSerializer, 429: DetailSerializer,
        },
        summary='Открыть диалог (по объявлению или по сделке)',
        description=(
            'Тело — ровно одно из двух полей:\n\n'
            '`{"listing_id": <id объявления>}` — обращение к владельцу объявления '
            'ещё до брони. Идемпотентно: повторный вызов с тем же listing_id тем же '
            'пользователем возвращает уже существующий диалог (200), а не создаёт новый '
            '(201 — только при первом создании). На объявление владельца открыть диалог '
            'самому себе нельзя (400). Если у пользователя уже есть '
            f'{getattr(settings, "CHAT_MAX_OPEN_INQUIRIES", 20)} открытых диалогов-обращений '
            '(без привязанной сделки) и это не один из них — 429.\n\n'
            'Когда по этой же паре «объявление + арендатор» позже появляется оплаченная '
            'сделка, диалог не дублируется: тот же Conversation получает deal_id (см. '
            'apps.payments.views.finalize_paid_payment).\n\n'
            '`{"deal_id": <id сделки>}` — диалог по уже оплаченной сделке (старый флоу, '
            'сохранён для обратной совместимости). Если диалог по сделке уже есть, '
            'возвращается он же. 403 — вызывающий не участник сделки либо сделка не оплачена '
            '(разрешены статусы paid, in_progress, returned, completed, disputed). '
            '404 — сделки/объявления нет.'
        ),
    ),
)
class ConversationListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    PAID_STATUSES = [
        Booking.STATUS_PAID,
        Booking.STATUS_IN_PROGRESS,
        Booking.STATUS_RETURNED,
        Booking.STATUS_COMPLETED,
        Booking.STATUS_DISPUTED,
    ]

    def get(self, request):
        qs = Conversation.objects.filter(participants=request.user).prefetch_related('participants', 'messages')
        return Response(ConversationSerializer(qs, many=True, context={'request': request}).data)

    def post(self, request):
        serializer = ConversationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data.get('listing_id'):
            return self._open_for_listing(request, data['listing_id'])
        return self._open_for_deal(request, data['deal_id'])

    def _open_for_listing(self, request, listing_id):
        try:
            item = Item.objects.select_related('owner').get(pk=listing_id, status=Item.STATUS_APPROVED)
        except Item.DoesNotExist:
            return Response({'detail': 'Объявление не найдено.'}, status=status.HTTP_404_NOT_FOUND)

        if item.owner_id == request.user.id:
            return Response(
                {'detail': 'Нельзя открыть диалог по собственному объявлению.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Идемпотентность: одна беседа на пару (объявление, арендатор), не на каждый клик.
        conversation = Conversation.objects.filter(listing=item, participants=request.user).first()
        created = False

        if not conversation:
            max_open = getattr(settings, 'CHAT_MAX_OPEN_INQUIRIES', 20)
            open_count = Conversation.objects.filter(participants=request.user, deal__isnull=True).count()
            if open_count >= max_open:
                return Response(
                    {'detail': f'Превышен лимит открытых диалогов без сделки ({max_open}).'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            conversation = Conversation.objects.create(listing=item)
            created = True

        conversation.participants.add(request.user, item.owner)
        conversation = (
            Conversation.objects
            .prefetch_related('participants', 'messages')
            .get(pk=conversation.pk)
        )
        return Response(
            ConversationSerializer(conversation, context={'request': request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def _open_for_deal(self, request, deal_id):
        try:
            deal = Booking.objects.select_related('item__owner', 'renter').get(pk=deal_id)
        except Booking.DoesNotExist:
            return Response({'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

        if request.user not in [deal.renter, deal.item.owner]:
            return Response({'detail': 'Нет доступа к сделке.'}, status=status.HTTP_403_FORBIDDEN)
        if deal.status not in self.PAID_STATUSES:
            return Response({'detail': 'Чат открывается после оплаты сделки'}, status=status.HTTP_403_FORBIDDEN)

        conversation = Conversation.objects.filter(deal=deal).first()
        created = False
        if not conversation:
            conversation = Conversation.objects.create(deal=deal, listing=deal.item)
            created = True
        conversation.participants.add(deal.renter, deal.item.owner)

        conversation = (
            Conversation.objects
            .prefetch_related('participants', 'messages')
            .get(pk=conversation.pk)
        )
        return Response(
            ConversationSerializer(conversation, context={'request': request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class MessageListView(generics.ListCreateAPIView):
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Message.objects.filter(
            conversation_id=self.kwargs['pk'],
            conversation__participants=self.request.user,
        ).select_related('sender', 'conversation')

    def perform_create(self, serializer):
        conversation = Conversation.objects.get(pk=self.kwargs['pk'], participants=self.request.user)
        serializer.save(conversation=conversation, sender=self.request.user)
        conversation.save(update_fields=['updated_at'])


@extend_schema(
    request=None,
    responses={200: ConversationReadResponseSerializer, 404: DetailSerializer},
    summary='Отметить диалог прочитанным',
    description=(
        'Помечает прочитанными входящие сообщения диалога (свои не трогает). '
        'Тело запроса не нужно. 404 — диалога нет либо вызывающий в нём не участвует.'
    ),
)
class ConversationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            conversation = Conversation.objects.get(pk=pk, participants=request.user)
        except Conversation.DoesNotExist:
            return Response({'detail': 'Conversation not found.'}, status=status.HTTP_404_NOT_FOUND)

        updated = conversation.messages.exclude(sender=request.user).filter(is_read=False).update(is_read=True)
        return Response({'detail': 'Conversation marked as read.', 'updated': updated})

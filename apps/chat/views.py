from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.models import Booking
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
        responses={201: ConversationSerializer, 403: DetailSerializer, 404: DetailSerializer},
        summary='Открыть диалог по сделке',
        description=(
            'Тело: {"deal_id": <id сделки>}. Если диалог по сделке уже есть, возвращается он же. '
            'Участниками становятся арендатор и владелец.\n\n'
            '403 — deal_id не передан, вызывающий не участник сделки либо сделка не оплачена '
            '(разрешены статусы paid, in_progress, returned, completed, disputed). '
            '404 — сделки нет.'
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
        if not request.data.get('deal_id'):
            return Response({'detail': 'Чат открывается после оплаты сделки'}, status=status.HTTP_403_FORBIDDEN)

        serializer = ConversationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            deal = Booking.objects.select_related('item__owner', 'renter').get(pk=data['deal_id'])
        except Booking.DoesNotExist:
            return Response({'detail': 'Сделка не найдена.'}, status=status.HTTP_404_NOT_FOUND)

        if request.user not in [deal.renter, deal.item.owner]:
            return Response({'detail': 'Нет доступа к сделке.'}, status=status.HTTP_403_FORBIDDEN)
        if deal.status not in self.PAID_STATUSES:
            return Response({'detail': 'Чат открывается после оплаты сделки'}, status=status.HTTP_403_FORBIDDEN)

        conversation = Conversation.objects.filter(deal=deal).first()
        if not conversation:
            conversation = Conversation.objects.create(deal=deal)
        conversation.participants.add(deal.renter, deal.item.owner)

        conversation = (
            Conversation.objects
            .prefetch_related('participants', 'messages')
            .get(pk=conversation.pk)
        )
        return Response(ConversationSerializer(conversation, context={'request': request}).data, status=status.HTTP_201_CREATED)


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

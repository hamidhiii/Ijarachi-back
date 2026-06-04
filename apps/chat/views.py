from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.models import Booking
from .models import Conversation, Message
from .serializers import ConversationCreateSerializer, ConversationSerializer, MessageSerializer


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


class ConversationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            conversation = Conversation.objects.get(pk=pk, participants=request.user)
        except Conversation.DoesNotExist:
            return Response({'detail': 'Conversation not found.'}, status=status.HTTP_404_NOT_FOUND)

        updated = conversation.messages.exclude(sender=request.user).filter(is_read=False).update(is_read=True)
        return Response({'detail': 'Conversation marked as read.', 'updated': updated})

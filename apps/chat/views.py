from django.contrib.auth import get_user_model
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.models import Booking
from apps.catalog.models import Item
from .models import Conversation, Message
from .serializers import ConversationCreateSerializer, ConversationSerializer, MessageSerializer

User = get_user_model()


class ConversationListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Conversation.objects.filter(participants=request.user).prefetch_related('participants', 'messages')
        return Response(ConversationSerializer(qs, many=True, context={'request': request}).data)

    def post(self, request):
        serializer = ConversationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        listing = None
        deal = None
        other_user = None

        if data.get('deal_id'):
            deal = Booking.objects.select_related('item__owner', 'renter').get(pk=data['deal_id'])
            if request.user not in [deal.renter, deal.item.owner]:
                return Response({'detail': 'Нет доступа к сделке.'}, status=status.HTTP_403_FORBIDDEN)
            other_user = deal.item.owner if request.user == deal.renter else deal.renter
        elif data.get('listing_id'):
            listing = Item.objects.select_related('owner').get(pk=data['listing_id'])
            other_user = listing.owner
        elif data.get('user_id'):
            other_user = User.objects.get(pk=data['user_id'])

        conversation = Conversation.objects.filter(
            participants=request.user,
        ).filter(participants=other_user, listing=listing, deal=deal).first()
        if not conversation:
            conversation = Conversation.objects.create(listing=listing, deal=deal)
            conversation.participants.add(request.user, other_user)

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

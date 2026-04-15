import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from apps.chat.models import ChatMessage
from apps.bookings.models import Booking

User = get_user_model()

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.booking_id = self.scope['url_route']['kwargs']['booking_id']
        self.room_group_name = f'chat_{self.booking_id}'
        self.user = self.scope.get('user')

        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        # Verify user is part of the booking
        is_allowed = await self.check_booking_permission(self.booking_id, self.user)
        if not is_allowed:
            await self.close()
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """
        Receive message from WebSocket.
        """
        data = json.loads(text_data)
        message_text = data.get('text')

        if not message_text:
            return

        # Save message to DB
        chat_message = await self.save_message(self.booking_id, self.user, message_text)
        
        # Determine recipient
        recipient_id = chat_message.recipient_id

        # Send message to room group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'id': chat_message.id,
                'text': chat_message.text,
                'sender_id': self.user.id,
                'sender_phone': self.user.phone,
                'recipient_id': recipient_id,
                'created_at': chat_message.created_at.isoformat(),
            }
        )

    async def chat_message(self, event):
        """
        Receive message from room group.
        """
        # Send message to WebSocket
        await self.send(text_data=json.dumps(event))

    @database_sync_to_async
    def check_booking_permission(self, booking_id, user):
        try:
            booking = Booking.objects.get(id=booking_id)
            # User must be either renter or owner
            return user == booking.renter or user == booking.item.owner
        except Booking.DoesNotExist:
            return False

    @database_sync_to_async
    def save_message(self, booking_id, sender, text):
        booking = Booking.objects.select_related('renter', 'item__owner').get(id=booking_id)
        # Recipient is the other party in the booking
        recipient = booking.item.owner if sender == booking.renter else booking.renter
        
        return ChatMessage.objects.create(
            booking=booking,
            sender=sender,
            recipient=recipient,
            text=text
        )

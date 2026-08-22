from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.group_name = f'chat_{self.conversation_id}'

        if not self.scope['user'].is_authenticated:
            await self.close()
            return
        if not await self._has_access():
            await self.close()
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        text = (content.get('text') or '').strip()
        if not text:
            return
        message = await self._create_message(text)
        await self.channel_layer.group_send(
            self.group_name,
            {'type': 'chat.message', 'message': message},
        )

    async def chat_message(self, event):
        await self.send_json(event['message'])

    @database_sync_to_async
    def _has_access(self):
        from .models import Conversation

        return Conversation.objects.filter(pk=self.conversation_id, participants=self.scope['user']).exists()

    @database_sync_to_async
    def _create_message(self, text):
        from .models import Conversation, Message

        conversation = Conversation.objects.get(pk=self.conversation_id)
        user = self.scope['user']
        message = Message.objects.create(conversation=conversation, sender=user, text=text)
        conversation.save(update_fields=['updated_at'])
        try:
            full_name = user.profile.full_name or user.phone
        except Exception:
            full_name = user.phone
        return {
            'id': message.pk,
            'conversation': conversation.pk,
            'sender': {'id': user.pk, 'full_name': full_name},
            'sender_phone': user.phone,
            'text': message.text,
            'is_read': False,
            'created_at': message.created_at.isoformat(),
        }

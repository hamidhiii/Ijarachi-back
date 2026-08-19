from channels.generic.websocket import AsyncJsonWebsocketConsumer


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """
    ws/notifications/ — личный канал пользователя для live push-уведомлений
    (заменяет FCM: доставляет, пока приложение открыто/в фоне с активным сокетом).
    """

    async def connect(self):
        user = self.scope['user']
        if not user.is_authenticated:
            await self.close()
            return
        self.group_name = f'notifications_{user.pk}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notify_push(self, event):
        await self.send_json(event['notification'])

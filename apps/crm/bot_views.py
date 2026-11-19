"""Webhook CRM-бота и привязка его к пользователю из кабинета."""
import hmac

from django.http import Http404, HttpResponse
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from . import bot_booking as booking
from . import telegram as bot
from .access import OwnerAccountMixin
from .models import CrmBotLink


class CrmBotWebhookView(APIView):
    """
    POST /api/v1/telegram/webhook/crm/ — обновления CRM-бота: /start <токен>,
    /bugun, нажатия кнопок. Подлинность — X-Telegram-Bot-Api-Secret-Token.
    """
    permission_classes = []
    authentication_classes = []
    throttle_classes = []

    def post(self, request):
        expected = bot.webhook_secret()
        received = request.META.get('HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN', '')
        if not expected or not hmac.compare_digest(expected, received):
            raise Http404

        update = request.data or {}
        callback = update.get('callback_query')
        if callback:
            if not bot.handle_callback(callback):
                bot.api('answerCallbackQuery', {'callback_query_id': callback.get('id')})
            return HttpResponse(status=200)

        message = update.get('message') or {}
        chat = message.get('chat') or {}
        text = message.get('text') or ''
        if chat.get('type') != 'private' or not chat.get('id') or not text:
            return HttpResponse(status=200)
        sender = message.get('from') or {}
        if text.startswith('/start'):
            bot.handle_start(chat['id'], sender, text)
        elif booking.is_new_command(text):
            booking.start(chat['id'], sender)
        elif bot.is_today_command(text) or booking.is_today_button(text):
            bot.send_today(chat['id'], sender)
        elif not booking.handle_text(chat['id'], sender, text):
            bot.send_help(chat['id'], sender)
        return HttpResponse(status=200)


TELEGRAM_STATE = inline_serializer('CrmBotState', {
    'available': serializers.BooleanField(help_text='Бот настроен на сервере'),
    'linked': serializers.BooleanField(),
    'username': serializers.CharField(help_text='@ того, кто подключил, или пусто'),
    'bot': serializers.CharField(help_text='@ бота'),
    'link': serializers.CharField(required=False, help_text='Только в ответе POST: одноразовая ссылка на час'),
})


class CrmBotLinkView(OwnerAccountMixin, APIView):
    """
    GET /owner/telegram/ — подключён ли мой Telegram к CRM-боту.
    POST — одноразовая ссылка t.me/<бот>?start=… (час). DELETE — отключить.
    Привязка личная (пользователь, не кабинет): менеджер подключает свой Telegram.
    """

    def _state(self, extra=None):
        from django.conf import settings

        link = CrmBotLink.objects.filter(user=self.request.user).first()
        return {
            'available': bool(bot.token() and settings.CRM_BOT_USERNAME),
            'linked': link is not None,
            'username': link.username if link else '',
            'bot': settings.CRM_BOT_USERNAME,
            **(extra or {}),
        }

    @extend_schema(responses=TELEGRAM_STATE)
    def get(self, request):
        return Response(self._state())

    @extend_schema(request=None, responses=TELEGRAM_STATE)
    def post(self, request):
        link = bot.invite_link(request.user)
        if link is None:
            return Response(
                {'code': 'CRM_BOT_UNAVAILABLE', 'detail': 'Telegram-бот ещё не настроен.'}, status=503,
            )
        return Response(self._state({'link': link}))

    @extend_schema(responses={204: None})
    def delete(self, request):
        CrmBotLink.objects.filter(user=request.user).delete()
        return Response(status=204)

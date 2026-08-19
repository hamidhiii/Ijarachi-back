import logging

from django.conf import settings
from django.http import Http404, HttpResponse
from django.utils import timezone
from rest_framework.views import APIView

from ..models import OTPCode, TelegramLink
from ..otp import generate_otp
from ..serializers import normalize_uz_phone
from ..telegram_bot import (
    LINKED_TEXT,
    PHONE_MISMATCH_TEXT,
    send_contact_request,
    send_otp_via_telegram,
    send_telegram_message,
)

logger = logging.getLogger(__name__)


class TelegramWebhookView(APIView):
    """
    POST /api/v1/telegram/webhook/<secret>/
    Принимает обновления от Telegram Bot API (long-poll заменён на webhook).
    """
    permission_classes = []
    authentication_classes = []

    def post(self, request, secret):
        if not settings.TELEGRAM_WEBHOOK_SECRET or secret != settings.TELEGRAM_WEBHOOK_SECRET:
            raise Http404

        update = request.data or {}
        message = update.get('message') or update.get('edited_message')
        if not message:
            return HttpResponse(status=200)

        chat = message.get('chat') or {}
        chat_id = chat.get('id')
        from_user = message.get('from') or {}

        contact = message.get('contact')
        text = message.get('text', '')

        if contact:
            self._handle_contact(chat_id, from_user, contact)
        elif text.startswith('/start'):
            send_contact_request(chat_id)

        return HttpResponse(status=200)

    def _handle_contact(self, chat_id, from_user, contact):
        # Требуем, чтобы контакт принадлежал самому пользователю бота (не переслан за кого-то).
        if contact.get('user_id') and contact.get('user_id') != from_user.get('id'):
            self._reply(chat_id, PHONE_MISMATCH_TEXT)
            return

        try:
            phone = normalize_uz_phone(contact.get('phone_number', ''))
        except Exception:
            self._reply(chat_id, PHONE_MISMATCH_TEXT)
            return

        TelegramLink.objects.update_or_create(
            phone=phone,
            defaults={
                'chat_id': chat_id,
                'telegram_user_id': from_user.get('id'),
                'username': from_user.get('username', '') or '',
                'updated_at': timezone.now(),
            },
        )
        logger.info('Telegram link created for %s (chat %s)', phone, chat_id)

        code = generate_otp()
        OTPCode.objects.create(phone=phone, code=code)
        self._reply(chat_id, LINKED_TEXT.format(phone=phone))
        send_otp_via_telegram(phone, code)

    @staticmethod
    def _reply(chat_id, text):
        send_telegram_message(chat_id, text, reply_markup={'remove_keyboard': True})

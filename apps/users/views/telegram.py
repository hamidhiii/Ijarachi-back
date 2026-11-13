import hmac
import logging
from datetime import timedelta

from django.conf import settings
from django.http import Http404, HttpResponse
from django.utils import timezone
from rest_framework.views import APIView

from .. import telegram_app_bot as app_bot
from ..models import OTPCode, TelegramLink
from ..otp import generate_otp
from ..serializers import normalize_uz_phone
from ..telegram_bot import (
    CODE_SENT_TEXT,
    CONFIRM_PHONE_TEXT,
    LINKED_TEXT,
    PHONE_MISMATCH_TEXT,
    parse_start_payload,
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
            self._handle_start(chat_id, text)

        return HttpResponse(status=200)

    def _handle_start(self, chat_id, text):
        """The deep link's payload, used without being trusted.

        The link the site opens carries the number the reader typed. That is a
        request, not a proof — anyone can put somebody else's number in a URL —
        so it is never enough to link a chat or release a code on its own.

        It is worth two things all the same. When this chat has ALREADY proved
        it owns that number by sharing its contact, there is nothing left to
        prove and the code goes out on the /start alone: no second button, which
        is the whole of what the deep link was for. And when it has not, the
        request can at least be named, so somebody who typed the wrong number
        finds out here rather than after sharing their contact and waiting for
        a code the site will never see.
        """
        phone = parse_start_payload(text)
        if not phone:
            send_contact_request(chat_id)
            return

        link = TelegramLink.objects.filter(phone=phone, chat_id=chat_id).first()
        if not link:
            # Either a number this chat has never confirmed, or one confirmed
            # from somebody else's Telegram. Both have the same answer: prove it.
            send_contact_request(chat_id, CONFIRM_PHONE_TEXT.format(phone=phone))
            return

        if self._cooling_down(phone):
            # The same window `POST /auth/send-otp/` enforces. Without it,
            # reopening the link is an unmetered way to mint codes.
            send_telegram_message(
                chat_id,
                f'Код уже отправлен. Следующий можно запросить через '
                f'{settings.OTP_RESEND_COOLDOWN_SECONDS} секунд.',
                reply_markup={'remove_keyboard': True},
            )
            return

        code = generate_otp()
        OTPCode.objects.create(phone=phone, code=code)
        self._reply(chat_id, CODE_SENT_TEXT.format(phone=phone))
        send_otp_via_telegram(phone, code)

    @staticmethod
    def _cooling_down(phone: str) -> bool:
        window = timezone.now() - timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
        return OTPCode.objects.filter(
            phone=phone, created_at__gte=window, is_used=False
        ).exists()

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


class TelegramAppBotWebhookView(APIView):
    """
    POST /api/v1/telegram/webhook/app/
    Обновления от @rentoo_app (бот Mini App). На /start и любой текст отвечает
    приветствием с кнопкой «Открыть Rentoo». Подлинность — заголовок
    X-Telegram-Bot-Api-Secret-Token (задаётся в setWebhook, см. setup_app_bot).
    """
    permission_classes = []
    authentication_classes = []
    # Все обновления приходят с немногих адресов Telegram — общий лимит 60/мин
    # на IP начал бы терять приветствия при первом же наплыве.
    throttle_classes = []

    def post(self, request):
        expected = app_bot.webhook_secret()
        received = request.META.get('HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN', '')
        if not expected or not hmac.compare_digest(expected, received):
            raise Http404

        message = (request.data or {}).get('message') or {}
        chat = message.get('chat') or {}
        # Только личные чаты: в группе приветствие на каждое сообщение — спам.
        if chat.get('type') == 'private' and chat.get('id') and 'text' in message:
            sender = message.get('from') or {}
            app_bot.send_welcome(chat['id'], app_bot.language(sender.get('language_code')))
        return HttpResponse(status=200)

import logging

import requests
from django.conf import settings

from .models import TelegramLink

logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    'Привет! Это бот Rentoo для подтверждения номера телефона.\n\n'
    'Нажмите кнопку ниже и поделитесь своим номером телефона — '
    'мы будем присылать сюда код подтверждения вместо SMS.'
)
LINKED_TEXT = 'Номер {phone} подтверждён. Код подтверждения отправлен ниже 👇'
PHONE_MISMATCH_TEXT = (
    'Этот номер телефона не привязан ни к одной попытке входа в Rentoo. '
    'Откройте приложение, введите номер и повторите отправку кода.'
)


def _api_url(method: str) -> str:
    return f'{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/{method}'


def send_telegram_message(chat_id: int, text: str, reply_markup: dict | None = None) -> bool:
    """Send a text message via the Telegram Bot API. Returns True on success."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning('TELEGRAM_BOT_TOKEN is not configured, cannot send Telegram message')
        return False
    payload = {'chat_id': chat_id, 'text': text}
    if reply_markup is not None:
        payload['reply_markup'] = reply_markup
    try:
        resp = requests.post(_api_url('sendMessage'), json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error('Telegram sendMessage failed for chat %s: %s', chat_id, exc)
        return False


def send_contact_request(chat_id: int) -> bool:
    keyboard = {
        'keyboard': [[{'text': '📱 Отправить номер телефона', 'request_contact': True}]],
        'resize_keyboard': True,
        'one_time_keyboard': True,
    }
    return send_telegram_message(chat_id, WELCOME_TEXT, reply_markup=keyboard)


def get_telegram_link(phone: str) -> TelegramLink | None:
    return TelegramLink.objects.filter(phone=phone).first()


def build_deep_link(phone: str) -> str | None:
    if not settings.TELEGRAM_BOT_USERNAME:
        return None
    payload = phone.lstrip('+')
    return f'https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={payload}'


def send_otp_via_telegram(phone: str, code: str) -> bool:
    link = get_telegram_link(phone)
    if not link:
        return False
    minutes = max(1, settings.OTP_EXPIRY_SECONDS // 60)
    text = f'Rentoo: ваш код подтверждения — {code}. Действителен {minutes} мин.'
    return send_telegram_message(link.chat_id, text, reply_markup={'remove_keyboard': True})

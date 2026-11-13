"""
@rentoo_app — the bot the Mini App lives in (not the OTP bot, @Rentoo_auth_bot).

It does one thing in chat: greet. /start, or anything else typed to it, is
answered with a welcome and an «Открыть Rentoo» button that opens the site as
a Mini App. Texts are Uzbek or Russian by the sender's Telegram language;
Uzbek is the default, as on the site.

Updates arrive at POST /api/v1/telegram/webhook/app/ (TelegramAppBotWebhookView),
registered — together with the bot's description — by
`manage.py setup_app_bot`.
"""

import hashlib
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

WELCOME = {
    'uz': (
        "Rentoo'ga xush kelibsiz! 👋\n\n"
        "Sotib olmang — ijaraga oling. Ko'ylak, kostyum, mebel, idish-tovoq, "
        "ovoz uskunalari va boshqalar — Toshkentda, yoningizdagi odamlardan.\n\n"
        "Pastdagi tugmani bosing 👇"
    ),
    'ru': (
        'Добро пожаловать в Rentoo! 👋\n\n'
        'Зачем покупать — берите в аренду. Платья, костюмы, мебель, посуда, '
        'звук и многое другое — в Ташкенте, у людей рядом с вами.\n\n'
        'Нажмите кнопку ниже 👇'
    ),
}
OPEN_BUTTON = {'uz': "🛍 Rentoo'ni ochish", 'ru': '🛍 Открыть Rentoo'}

# «What can this bot do?» — shown in the empty chat before Start. ≤ 512 chars.
DESCRIPTION = {
    'uz': (
        "Rentoo — Toshkentda buyumlar ijarasi.\n"
        "Ko'ylak, kostyum, mebel, idish-tovoq, ovoz uskunalari — yoningizdagi odamlardan.\n\n"
        "Kerakli narsani toping, kunlarni tanlang va o'zingiz olib keting."
    ),
    'ru': (
        'Rentoo — аренда вещей в Ташкенте.\n'
        'Платья, костюмы, мебель, посуда, звук — у людей рядом с вами.\n\n'
        'Найдите нужное, выберите дни и заберите сами.'
    ),
}
# Under the name on the bot's profile and in shared links. ≤ 120 chars.
SHORT_DESCRIPTION = {
    'uz': "Toshkentda buyumlar ijarasi: ko'ylak, kostyum, mebel, idish, ovoz uskunalari.",
    'ru': 'Аренда вещей в Ташкенте: платья, костюмы, мебель, посуда, звук.',
}


def token() -> str:
    return settings.TELEGRAM_WEBAPP_BOT_TOKEN


def webhook_secret() -> str:
    """Sent by Telegram in X-Telegram-Bot-Api-Secret-Token on every update.

    Derived from the bot token so there is no second secret to keep in .env;
    anyone who could compute it already holds the token itself.
    """
    if not token():
        return ''
    return hashlib.sha256(f'rentoo-app-webhook:{token()}'.encode()).hexdigest()


def language(code: str | None) -> str:
    return 'ru' if (code or '').lower().startswith('ru') else 'uz'


def api(method: str, payload: dict) -> dict:
    """Calls the Bot API as @rentoo_app. Never lets the token reach a log."""
    url = f'{settings.TELEGRAM_API_BASE_URL}/bot{token()}/{method}'
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as exc:  # noqa: BLE001 — network, JSON; both just fail the call
        message = str(exc).replace(token(), '***') if token() else str(exc)
        logger.error('@rentoo_app %s failed: %s', method, message)
        return {'ok': False, 'description': message}


def welcome_payload(chat_id: int, lang: str) -> dict:
    return {
        'chat_id': chat_id,
        'text': WELCOME[lang],
        'reply_markup': {
            'inline_keyboard': [[{
                'text': OPEN_BUTTON[lang],
                'web_app': {'url': settings.FRONTEND_BASE_URL.rstrip('/') + '/'},
            }]],
        },
    }


def send_welcome(chat_id: int, lang: str) -> bool:
    return bool(api('sendMessage', welcome_payload(chat_id, lang)).get('ok'))

"""
Telegram Mini App sign-in: checking the `initData` a Mini App is launched with.

When rentoo.uz is opened from the bot's menu button, Telegram hands the page a
query string (`Telegram.WebApp.initData`) describing who opened it, signed with
a key derived from the bot token. The page posts it to
`POST /api/v1/auth/telegram/`; this module decides whether it is genuine.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

The Mini App lives in @rentoo_app, while OTP codes come from @Rentoo_auth_bot;
initData is signed with the token of the bot it was opened from, so
TELEGRAM_WEBAPP_BOT_TOKEN is checked as well as TELEGRAM_BOT_TOKEN. A Telegram
user id is the same in every bot, so the link made in the OTP bot applies.

The signature proves *which Telegram account* opened the app — nothing about a
phone number. The phone comes from `TelegramLink`, which only ever records a
number its owner shared from that same account with the bot's «Отправить
номер» button (see TelegramWebhookView._handle_contact). That pair — signed
Telegram id, number proven by that id — is the same proof an OTP sign-in rests
on, since the OTP is delivered to exactly that chat.
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from django.conf import settings

from .models import TelegramLink

# initData is minted when the Mini App opens and does not change while it
# stays open. A day covers a long session; anything older is a replay.
MAX_AGE_SECONDS = 24 * 60 * 60
# Clocks drift; a signature from slightly in the future is not an attack.
FUTURE_SKEW_SECONDS = 60


@dataclass(frozen=True)
class TelegramUser:
    id: int
    username: str
    first_name: str
    language_code: str


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()


def verify_init_data(
    init_data: str,
    bot_token: str | None = None,
    now: float | None = None,
) -> TelegramUser | None:
    """The Telegram user `init_data` was signed for, or None if it is not genuine.

    None covers every way it can fail — missing, malformed, wrong signature,
    expired, no user — because the caller's answer to all of them is the same.
    """
    if bot_token is None:
        # The Mini App bot (@rentoo_app) and the OTP bot are different bots;
        # data from either is genuine if its own token signed it.
        tokens = [t for t in (settings.TELEGRAM_WEBAPP_BOT_TOKEN, settings.TELEGRAM_BOT_TOKEN) if t]
    else:
        tokens = [bot_token] if bot_token else []
    if not init_data or not tokens or len(init_data) > 4096:
        return None

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    fields = dict(pairs)
    if len(fields) != len(pairs):
        # A repeated key: which copy was signed is ambiguous, so neither is.
        return None

    received = fields.pop('hash', '')
    if not received:
        return None
    # Every field but `hash` is signed, `signature` (the Ed25519 one meant for
    # third parties) included — sorted by key, one `key=value` per line.
    check_string = '\n'.join(f'{key}={fields[key]}' for key in sorted(fields))
    signed = any(
        hmac.compare_digest(
            hmac.new(_secret_key(token), check_string.encode(), hashlib.sha256).hexdigest(),
            received.lower(),
        )
        for token in tokens
    )
    if not signed:
        return None

    try:
        auth_date = int(fields.get('auth_date', ''))
    except ValueError:
        return None
    now = time.time() if now is None else now
    if auth_date > now + FUTURE_SKEW_SECONDS or now - auth_date > MAX_AGE_SECONDS:
        return None

    try:
        user = json.loads(fields.get('user', ''))
        user_id = int(user['id'])
    except (ValueError, TypeError, KeyError):
        return None
    if user_id <= 0:
        return None

    return TelegramUser(
        id=user_id,
        username=str(user.get('username') or ''),
        first_name=str(user.get('first_name') or ''),
        language_code=str(user.get('language_code') or ''),
    )


def link_for(telegram_user_id: int) -> TelegramLink | None:
    """The number this Telegram account has proven to the bot, newest first.

    Rows written before `telegram_user_id` was recorded still have `chat_id`,
    which for a private chat with the bot *is* the user's id.
    """
    return (
        TelegramLink.objects.filter(telegram_user_id=telegram_user_id).order_by('-updated_at').first()
        or TelegramLink.objects.filter(chat_id=telegram_user_id, telegram_user_id__isnull=True)
        .order_by('-updated_at')
        .first()
    )

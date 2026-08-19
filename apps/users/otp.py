import logging

from django.conf import settings

from .sms import generate_otp, send_otp_sms
from .telegram_bot import build_deep_link, get_telegram_link, send_otp_via_telegram

logger = logging.getLogger(__name__)

__all__ = ['generate_otp', 'send_otp', 'telegram_link_required']


def _bot_configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_BOT_USERNAME)


def telegram_link_required(phone: str) -> bool:
    """True if the phone has no Telegram bot link and SMS fallback is disabled."""
    if settings.OTP_SMS_FALLBACK_ENABLED:
        return False
    if settings.DEBUG and not _bot_configured():
        # Local dev without a configured bot: skip the Telegram-link step.
        return False
    return get_telegram_link(phone) is None


def send_otp(phone: str, code: str) -> bool:
    """
    Deliver an OTP code. Prefers Telegram (номер уже привязан к боту),
    falls back to SMS only if OTP_SMS_FALLBACK_ENABLED is on.
    """
    if send_otp_via_telegram(phone, code):
        return True
    if settings.OTP_SMS_FALLBACK_ENABLED:
        return send_otp_sms(phone, code)
    if settings.DEBUG and not _bot_configured():
        logger.info('[DEV] OTP for %s: %s', phone, code)
        return True
    return False


def telegram_deep_link(phone: str) -> str | None:
    return build_deep_link(phone)

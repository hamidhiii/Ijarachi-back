import hmac
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import F

from .sms import generate_otp, send_otp_sms
from .telegram_bot import build_deep_link, get_telegram_link, send_otp_via_telegram

logger = logging.getLogger(__name__)

__all__ = ['check_code', 'generate_otp', 'send_otp', 'telegram_link_required']


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


def check_code(active_codes, code: str):
    """
    Сверяет введённый код с живыми кодами (queryset OTPCode/PhoneChangeRequest:
    не использованы, не истекли). Совпал — код гасится и возвращается.
    Не совпал — всем живым кодам прибавляется попытка, а достигшие
    OTP_MAX_ATTEMPTS гасятся: подбор шести цифр упирается в лимит раньше,
    чем в ограничение частоты запросов.

    Возвращает (совпавший код | None, сколько живых кодов осталось).
    """
    model = active_codes.model
    with transaction.atomic():
        rows = list(active_codes.select_for_update().order_by('-created_at'))
        match = next((row for row in rows if hmac.compare_digest(row.code, code)), None)
        if match is not None:
            match.is_used = True
            match.save(update_fields=['is_used'])
            return match, len(rows) - 1

        ids = [row.pk for row in rows]
        model.objects.filter(pk__in=ids).update(attempts=F('attempts') + 1)
        model.objects.filter(pk__in=ids, attempts__gte=settings.OTP_MAX_ATTEMPTS).update(is_used=True)
        remaining = model.objects.filter(pk__in=ids, is_used=False).count()
        return None, remaining

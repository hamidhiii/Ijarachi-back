import random
import string
import logging
from django.conf import settings
import requests

logger = logging.getLogger(__name__)


def _get_eskiz_token() -> str | None:
    """Obtain bearer token from Eskiz.uz."""
    try:
        resp = requests.post(f'{settings.ESKIZ_BASE_URL}/auth/login', data={
            'email': settings.ESKIZ_EMAIL,
            'password': settings.ESKIZ_PASSWORD,
        }, timeout=settings.SMS_REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json()['data']['token']
    except Exception as exc:
        logger.error('Eskiz auth failed: %s', exc)
        return None


def send_sms(phone: str, message: str) -> bool:
    """Send a raw SMS message via Eskiz.uz. Returns True on success."""
    token = _get_eskiz_token()
    if not token:
        return False
    try:
        resp = requests.post(
            f'{settings.ESKIZ_BASE_URL}/message/sms/send',
            headers={'Authorization': f'Bearer {token}'},
            data={
                'mobile_phone': phone.lstrip('+'),
                'message': message,
                'from': settings.ESKIZ_SENDER_ID,
            },
            timeout=settings.SMS_REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error('Eskiz SMS send failed for %s: %s', phone, exc)
        return False


def send_otp_sms(phone: str, code: str) -> bool:
    """Send OTP via Eskiz.uz. Returns True on success."""
    if settings.DEBUG and not settings.ESKIZ_EMAIL:
        # In development — just log the code
        logger.info('[DEV] OTP for %s: %s', phone, code)
        return True

    minutes = max(1, settings.OTP_EXPIRY_SECONDS // 60)
    message = f'Rentoo: ваш код подтверждения — {code}. Действителен {minutes} мин.'
    return send_sms(phone, message)


def generate_otp(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))

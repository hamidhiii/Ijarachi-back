import random
import string
import logging
from django.conf import settings
import requests

logger = logging.getLogger(__name__)

ESKIZ_TOKEN_URL = 'https://notify.eskiz.uz/api/auth/login'
ESKIZ_SEND_URL = 'https://notify.eskiz.uz/api/message/sms/send'


def _get_eskiz_token() -> str | None:
    """Obtain bearer token from Eskiz.uz."""
    try:
        resp = requests.post(ESKIZ_TOKEN_URL, data={
            'email': settings.ESKIZ_EMAIL,
            'password': settings.ESKIZ_PASSWORD,
        }, timeout=10)
        resp.raise_for_status()
        return resp.json()['data']['token']
    except Exception as exc:
        logger.error('Eskiz auth failed: %s', exc)
        return None


def send_otp_sms(phone: str, code: str) -> bool:
    """Send OTP via Eskiz.uz. Returns True on success."""
    if settings.DEBUG and not settings.ESKIZ_EMAIL:
        # In development — just log the code
        logger.info('[DEV] OTP for %s: %s', phone, code)
        return True

    token = _get_eskiz_token()
    if not token:
        return False

    message = f'Rentoo: ваш код подтверждения — {code}. Действителен 2 минуты.'
    try:
        resp = requests.post(
            ESKIZ_SEND_URL,
            headers={'Authorization': f'Bearer {token}'},
            data={
                'mobile_phone': phone.lstrip('+'),
                'message': message,
                'from': '4546',
            },
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error('Eskiz SMS send failed for %s: %s', phone, exc)
        return False


def generate_otp(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))

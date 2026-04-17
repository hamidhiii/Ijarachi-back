import logging
from django.core.mail import send_mail
from django.conf import settings
import string
import secrets

logger = logging.getLogger(__name__)


def generate_otp(length: int = 6) -> str:
    """Generate a random numeric OTP code."""
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def send_otp_email(email: str, code: str) -> bool:
    """Send OTP code to the user's email."""
    subject = 'Код подтверждения SYNTH Share'
    message = f'Ваш код подтверждения: {code}\nДействителен в течение 2 минут.'
    
    if settings.DEBUG and not settings.EMAIL_HOST_USER:
        logger.info('[DEV] Email OTP for %s: %s', email, code)
        return True

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        return True
    except Exception as exc:
        logger.error('Failed to send OTP email to %s: %s', email, exc)
        return False

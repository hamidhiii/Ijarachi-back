import logging

from .models import AuthEvent

logger = logging.getLogger(__name__)


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    # Один nginx перед Django (см. NUM_PROXIES): настоящий адрес — последний хоп.
    ip = forwarded.split(',')[-1].strip() if forwarded else request.META.get('REMOTE_ADDR', '')
    return ip or None


def record(request, event, phone='', detail=''):
    """Записать шаг входа. Аналитика не должна ронять вход, поэтому ошибки глотаем."""
    try:
        data = getattr(request, 'data', None) or {}
        visitor_id = str(data.get('visitor_id') or request.META.get('HTTP_X_VISITOR_ID') or '')[:64]
        AuthEvent.objects.create(
            event=event,
            phone=(phone or '')[:20],
            visitor_id=visitor_id,
            ip=_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:200],
            detail=str(detail)[:300],
        )
    except Exception:
        logger.exception('Не удалось записать событие входа %s', event)

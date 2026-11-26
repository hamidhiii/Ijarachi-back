import logging
from urllib.parse import urlsplit

from .models import AuthEvent

logger = logging.getLogger(__name__)


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    # Один nginx перед Django (см. NUM_PROXIES): настоящий адрес — последний хоп.
    ip = forwarded.split(',')[-1].strip() if forwarded else request.META.get('REMOTE_ADDR', '')
    return ip or None


def site_of(request):
    """
    С какого сайта запрос: owner.rentoo.uz → owner, иначе web. Оба фронта ходят
    в API через свой же домен (/backend/), а браузер ставит Origin на каждый
    POST — по нему и различаем. Без Origin смотрим Referer; Mini App передаёт
    источник явно (source=tma).
    """
    header = request.META.get('HTTP_ORIGIN') or request.META.get('HTTP_REFERER') or ''
    host = (urlsplit(header).hostname or '').lower()
    return AuthEvent.SOURCE_OWNER if host.startswith('owner.') else AuthEvent.SOURCE_WEB


def record(request, event, phone='', detail='', source=None):
    """Записать шаг входа. Аналитика не должна ронять вход, поэтому ошибки глотаем."""
    try:
        data = getattr(request, 'data', None) or {}
        visitor_id = str(data.get('visitor_id') or request.META.get('HTTP_X_VISITOR_ID') or '')[:64]
        if source not in dict(AuthEvent.SOURCE_CHOICES):
            source = site_of(request)
        AuthEvent.objects.create(
            event=event,
            source=source,
            phone=(phone or '')[:20],
            visitor_id=visitor_id,
            ip=_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:200],
            detail=str(detail)[:300],
        )
    except Exception:
        logger.exception('Не удалось записать событие входа %s', event)

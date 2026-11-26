"""
Кто сейчас на сайте — по пингам с фронта (POST /api/v1/analytics/ping/).

Каждая открытая вкладка rentoo.uz, owner.rentoo.uz или Mini App раз в минуту
шлёт {visitor_id, source}; вошедший — ещё и свой JWT. Всё живёт в Redis,
не в базе: это поток мелких записей, который через день никому не нужен.

    presence:v            ZSET  visitor → время последнего пинга
    presence:u            ZSET  user_id → время последнего пинга (35 дней — WAU/MAU)
    presence:src:<src>    ZSET  visitor → время (web / owner / tma)
    hll:v:<YYYYMMDD>      HyperLogLog уникальных посетителей за день (120 дней)
    hll:u:<YYYYMMDD>      HyperLogLog уникальных вошедших за день (DAU)
    hll:v:<src>:<YYYYMMDD>, hll:u:<src>:<YYYYMMDD>  то же по сайту (web / owner / tma)
    peak:<YYYYMMDD>       максимум «онлайн сейчас» за день

«Онлайн» — пинг за последние ONLINE_SECONDS. Первый пинг посетителя за день
пишет событие VISIT в AuthEvent — так воронка входа видит, сколько пришло.
Любой сбой Redis тихо проглатывается: мониторинг не должен ломать сайт.
"""
import logging
import re
import time
from datetime import date, timedelta

from django.utils import timezone

logger = logging.getLogger('apps.monitoring')

ONLINE_SECONDS = 150
SOURCES = ('web', 'owner', 'tma')
DAY_TTL = 120 * 24 * 3600
USERS_KEEP = 35 * 24 * 3600
VISITOR_ID = re.compile(r'^[A-Za-z0-9_-]{8,64}$')


def _redis():
    from django_redis import get_redis_connection

    return get_redis_connection('default')


def _day(value=None):
    return (value or timezone.localdate()).strftime('%Y%m%d')


def valid_visitor(value):
    return bool(value) and bool(VISITOR_ID.match(str(value)))


def ping(visitor_id, source='web', user_id=None):
    """Отметить посетителя. Возвращает True, если это его первый пинг за сегодня."""
    source = source if source in SOURCES else 'web'
    now = time.time()
    day = _day()
    try:
        r = _redis()
        pipe = r.pipeline()
        pipe.zadd('presence:v', {visitor_id: now})
        pipe.zadd(f'presence:src:{source}', {visitor_id: now})
        pipe.pfadd(f'hll:v:{day}', visitor_id)
        pipe.expire(f'hll:v:{day}', DAY_TTL)
        # По сайту отдельно: rentoo.uz и owner.rentoo.uz — разные аудитории,
        # а общий счётчик их смешивает (один человек на обоих — в каждом по разу).
        pipe.pfadd(f'hll:v:{source}:{day}', visitor_id)
        pipe.expire(f'hll:v:{source}:{day}', DAY_TTL)
        if user_id:
            pipe.zadd('presence:u', {str(user_id): now})
            pipe.pfadd(f'hll:u:{day}', str(user_id))
            pipe.expire(f'hll:u:{day}', DAY_TTL)
            pipe.pfadd(f'hll:u:{source}:{day}', str(user_id))
            pipe.expire(f'hll:u:{source}:{day}', DAY_TTL)
        # Первый пинг посетителя за сегодня.
        pipe.set(f'visit:{day}:{visitor_id}', 1, nx=True, ex=2 * 24 * 3600)
        result = pipe.execute()
        first_today = bool(result[-1])
        _cleanup_and_peak(r, now, day)
        return first_today
    except Exception as exc:  # noqa: BLE001
        logger.warning('presence ping failed: %s', exc)
        return False


def _cleanup_and_peak(r, now, day):
    # Чистим не каждый пинг: старые хвосты лишь занимают память.
    if int(now) % 10 == 0:
        r.zremrangebyscore('presence:v', 0, now - 24 * 3600)
        for source in SOURCES:
            r.zremrangebyscore(f'presence:src:{source}', 0, now - 24 * 3600)
        r.zremrangebyscore('presence:u', 0, now - USERS_KEEP)
    online = r.zcount('presence:v', now - ONLINE_SECONDS, '+inf')
    key = f'peak:{day}'
    peak = int(r.get(key) or 0)
    if online > peak:
        r.set(key, online, ex=DAY_TTL)


def live():
    """Онлайн сейчас: посетители, вошедшие, по источникам, пик за сегодня."""
    now = time.time()
    since = now - ONLINE_SECONDS
    try:
        r = _redis()
        pipe = r.pipeline()
        pipe.zcount('presence:v', since, '+inf')
        pipe.zcount('presence:u', since, '+inf')
        for source in SOURCES:
            pipe.zcount(f'presence:src:{source}', since, '+inf')
        pipe.get(f'peak:{_day()}')
        pipe.zcount('presence:u', now - 24 * 3600, '+inf')
        pipe.zcount('presence:u', now - 7 * 24 * 3600, '+inf')
        pipe.zcount('presence:u', now - 30 * 24 * 3600, '+inf')
        pipe.pfcount(f'hll:v:{_day()}')
        values = pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning('presence live failed: %s', exc)
        return {'available': False}
    online, users = values[0], values[1]
    by_source = dict(zip(SOURCES, values[2:2 + len(SOURCES)]))
    rest = values[2 + len(SOURCES):]
    return {
        'available': True,
        'online': online,
        'online_users': users,
        'online_guests': max(online - users, 0),
        'by_source': by_source,
        'peak_today': max(int(rest[0] or 0), online),
        'active_24h': rest[1],
        'active_7d': rest[2],
        'active_30d': rest[3],
        'visitors_today': rest[4],
        'at': timezone.now().isoformat(),
    }


def daily_counts(prefix, start: date, end: date):
    """{дата: число} уникальных за каждый день — из HyperLogLog (точность ~1%)."""
    days = []
    day = start
    while day <= end:
        days.append(day)
        day += timedelta(days=1)
    try:
        r = _redis()
        pipe = r.pipeline()
        for day in days:
            pipe.pfcount(f'{prefix}:{_day(day)}')
        counts = pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning('presence daily failed: %s', exc)
        counts = [0] * len(days)
    return {day: int(count) for day, count in zip(days, counts)}


def unique_over(prefix, start: date, end: date):
    """Уникальных за весь период (объединение дневных HyperLogLog)."""
    keys = []
    day = start
    while day <= end:
        keys.append(f'{prefix}:{_day(day)}')
        day += timedelta(days=1)
    try:
        return int(_redis().pfcount(*keys)) if keys else 0
    except Exception as exc:  # noqa: BLE001
        logger.warning('presence unique failed: %s', exc)
        return 0


def last_seen(user_ids):
    """{user_id: datetime} — когда вошедший пользователь последний раз был на сайте (35 дней)."""
    from datetime import datetime, timezone as dt_timezone

    ids = [str(pk) for pk in user_ids]
    if not ids:
        return {}
    try:
        pipe = _redis().pipeline()
        for pk in ids:
            pipe.zscore('presence:u', pk)
        scores = pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning('presence last_seen failed: %s', exc)
        return {}
    return {int(pk): datetime.fromtimestamp(score, tz=dt_timezone.utc) for pk, score in zip(ids, scores) if score}

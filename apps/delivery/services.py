from decimal import Decimal
from math import asin, cos, radians, sin, sqrt

from django.core.cache import cache


def _distance_km(from_lat, from_lng, to_lat, to_lng) -> Decimal:
    lat1, lng1, lat2, lng2 = map(radians, [from_lat, from_lng, to_lat, to_lng])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return Decimal(str(6371 * 2 * asin(sqrt(a)))).quantize(Decimal('0.01'))


def calculate_delivery_quote(from_lat, from_lng, to_lat, to_lng):
    if from_lat is None or from_lng is None:
        return {
            'cost': Decimal('0'),
            'distance_km': Decimal('0'),
            'currency': 'UZS',
            'provider': 'manual',
            'cached': False,
        }

    key = f'delivery:{from_lat}:{from_lng}:{to_lat}:{to_lng}'
    cached = cache.get(key)
    if cached:
        cached['cached'] = True
        return cached

    distance = _distance_km(float(from_lat), float(from_lng), float(to_lat), float(to_lng))
    base = Decimal('12000')
    per_km = Decimal('3500')
    cost = (base + distance * per_km).quantize(Decimal('1'))
    quote = {
        'cost': cost,
        'distance_km': distance,
        'currency': 'UZS',
        'provider': 'yandex',
        'cached': False,
    }
    cache.set(key, quote, timeout=30 * 60)
    return quote

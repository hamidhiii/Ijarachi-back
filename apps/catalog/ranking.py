"""
Порядок выдачи объявлений (решение 16.11.2026): VIP > топ > приоритет
тарифов BUSINESS/PRO > дата. Продвижение и приоритет действуют, пока не истёк
их срок, поэтому порядок считается выражениями от текущего времени.
"""
from django.db.models import BooleanField, Case, Q, Value, When
from django.utils import timezone


def _active(condition):
    return Case(When(condition, then=Value(True)), default=Value(False), output_field=BooleanField())


def promotion_ordering(now=None):
    """VIP, затем топ — для любого queryset объявлений."""
    now = now or timezone.now()
    return [
        _active(Q(vip_until__gt=now)).desc(),
        _active(Q(top_until__gt=now)).desc(),
    ]


def search_ordering(now=None):
    now = now or timezone.now()
    priority = _active(Q(
        owner__subscription__ends_at__gt=now,
        owner__subscription__plan__search_priority=True,
    ))
    return [*promotion_ordering(now), priority.desc(), '-created_at', '-pk']

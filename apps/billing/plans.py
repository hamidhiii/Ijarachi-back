"""Какой тариф действует у пользователя прямо сейчас и что он разрешает."""
from django.utils import timezone

from .models import Plan, Subscription

# Если миграция с тарифами почему-то не накатилась — бесплатный тариф всё равно
# есть, и лимит FREE работает.
_FALLBACK_FREE = Plan(code=Plan.FREE, name='FREE', price=0, listing_limit=10, rank=0)


def free_plan() -> Plan:
    return Plan.objects.filter(code=Plan.FREE).first() or _FALLBACK_FREE


def active_subscription(user):
    """Подписка, которая действует сейчас, или None (тогда пользователь на FREE)."""
    if not user or not user.is_authenticated:
        return None
    return (
        Subscription.objects.select_related('plan')
        .filter(user=user, ends_at__gt=timezone.now())
        .first()
    )


def current_plan(user) -> Plan:
    subscription = active_subscription(user)
    return subscription.plan if subscription else free_plan()

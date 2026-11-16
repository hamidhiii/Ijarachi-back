"""Какой тариф действует у пользователя прямо сейчас и что он разрешает."""
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException

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


FEATURE_PLAN = {
    'search_priority': Plan.BUSINESS,
    'staff_access': Plan.BUSINESS,
    'statistics': Plan.BUSINESS,
    'branches': Plan.PRO,
    'data_export': Plan.PRO,
}


class PlanFeatureRequired(APIException):
    """403 {code: PLAN_FEATURE_REQUIRED, feature, required_plan}."""
    status_code = status.HTTP_403_FORBIDDEN
    default_code = 'PLAN_FEATURE_REQUIRED'

    def __init__(self, feature, plan):
        super().__init__()
        required = FEATURE_PLAN.get(feature, Plan.PRO)
        self.detail = {
            'code': self.default_code,
            'detail': f'Доступно на тарифе {required.upper()} и выше. Сейчас у вас {plan.name}.',
            'feature': feature,
            'required_plan': required,
            'current_plan': plan.code,
        }


def has_feature(user, feature) -> bool:
    return bool(getattr(current_plan(user), feature))


def require_feature(user, feature):
    plan = current_plan(user)
    if not getattr(plan, feature):
        raise PlanFeatureRequired(feature, plan)
    return plan

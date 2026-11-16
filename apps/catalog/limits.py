"""
Лимит активных объявлений по тарифу (решение 16.11.2026): FREE 10, START 100,
BUSINESS 300, PRO без лимита — см. apps.billing.

«Активное» — объявление, которое видят арендаторы или модератор: на модерации
или опубликованное. Снятые, отклонённые и заблокированные не считаются.

Проверка стоит везде, где число активных растёт: создание и активация (возврат
снятого или отклонённого на модерацию). Обе вызывают её под блокировкой строки
пользователя, чтобы два параллельных запроса не проскочили лимит вместе.
Уже активные объявления лимит не трогает — их снимает только окончание тарифа.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.exceptions import APIException

from .models import Item

LIVE_STATUSES = (Item.STATUS_PENDING, Item.STATUS_APPROVED)
LIMIT_REACHED = 'LIMIT_REACHED'


class LimitReached(APIException):
    """400 {code, detail, plan, limit, active}; числа остаются числами (ValidationError делает их строками)."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = LIMIT_REACHED

    def __init__(self, plan, active):
        super().__init__()
        self.detail = {
            'code': LIMIT_REACHED,
            'detail': (
                f'На тарифе {plan.name} можно держать не больше {plan.listing_limit} '
                'активных объявлений. Снимите одно из старых или перейдите на тариф выше.'
            ),
            'plan': plan.code,
            'limit': plan.listing_limit,
            'active': active,
        }


def live_listing_count(user):
    return Item.objects.filter(owner=user, status__in=LIVE_STATUSES).count()


def listing_limit(user):
    """Сколько объявлений может быть активно; None — без лимита."""
    from apps.billing.plans import current_plan

    return current_plan(user).listing_limit


def enforce_listing_limit(user, adding=1):
    """
    Бросает 400 `LIMIT_REACHED`, если ещё `adding` активных объявлений превысят
    лимит тарифа. Вызывать внутри transaction.atomic — блокирует строку пользователя.
    """
    from apps.billing.plans import current_plan

    get_user_model().objects.select_for_update().filter(pk=user.pk).first()
    plan = current_plan(user)
    if plan.listing_limit is None:
        return
    live = live_listing_count(user)
    if live + adding > plan.listing_limit:
        raise LimitReached(plan, live)

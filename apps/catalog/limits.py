"""
Лимит объявлений по типу аккаунта (решение 27.10.2026).

«В работе» — объявление, которое видят арендаторы или модератор: на модерации
или опубликованное. Снятые и отклонённые не считаются — их можно держать
сколько угодно, лимит упирается только в то, что выставлено.

Проверка стоит в двух местах, где число таких объявлений растёт: создание и
возврат снятого/отклонённого на модерацию. Обе вызывают её под блокировкой
строки пользователя, чтобы два параллельных запроса не проскочили лимит вместе.
"""
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError

from .models import Item

LIVE_STATUSES = (Item.STATUS_PENDING, Item.STATUS_APPROVED)


def live_listing_count(user):
    return Item.objects.filter(owner=user, status__in=LIVE_STATUSES).count()


def listing_limit(user):
    from apps.users.models import Profile

    profile, _ = Profile.objects.get_or_create(user=user)
    return profile.listing_limit, profile.is_shop


def enforce_listing_limit(user):
    """
    Бросает 400 `listing_limit`, если ещё одно объявление в работе превысит
    лимит. Вызывать внутри transaction.atomic — блокирует строку пользователя.
    """
    get_user_model().objects.select_for_update().filter(pk=user.pk).first()
    limit, is_shop = listing_limit(user)
    if live_listing_count(user) >= limit:
        detail = (
            f'У магазина может быть не больше {limit} объявлений одновременно. Снимите одно из старых.'
            if is_shop else
            f'Частное лицо может держать не больше {limit} объявлений одновременно. '
            'Снимите одно из старых или переключите профиль на магазин.'
        )
        raise ValidationError({'code': 'listing_limit', 'detail': detail})

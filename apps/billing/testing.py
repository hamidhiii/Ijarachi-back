"""Помощники для тестов тарифов."""
from apps.billing.models import Plan
from apps.billing.services import extend_subscription


def give_plan(user, code, days=30):
    return extend_subscription(user, Plan.objects.get(code=code), days=days, replace_active=True)


def listing_payload(category, **extra):
    return {
        'title': 'Стул Кьявари', 'description': 'Белый', 'category': category.pk,
        'price_per_day': '15000', 'deposit': '0', 'condition': 'good',
        'address': 'Ташкент', 'city': 'Ташкент', **extra,
    }

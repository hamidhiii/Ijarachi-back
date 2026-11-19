"""
Платное продвижение объявления (решение 16.11.2026): «Поднять в топ» и VIP,
разовая оплата через Click/Payme, со сроком действия. Повторная покупка того
же вида продлевает срок от текущего окончания. Порядок выдачи — apps.catalog.ranking.
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import BillingOrder, Promotion
from .services import BillingError, _notify

FIELD = {BillingOrder.PROMO_TOP: 'top_until', BillingOrder.PROMO_VIP: 'vip_until'}


def promotion_price(kind):
    return settings.PROMO_TOP_PRICE if kind == BillingOrder.PROMO_TOP else settings.PROMO_VIP_PRICE


def promotion_days(kind):
    return settings.PROMO_TOP_DAYS if kind == BillingOrder.PROMO_TOP else settings.PROMO_VIP_DAYS


def promotion_offers():
    """Для GET /billing/promotions/: что можно купить и почём."""
    return [
        {'kind': kind, 'name': name, 'price': promotion_price(kind), 'days': promotion_days(kind)}
        for kind, name in BillingOrder.PROMO_CHOICES
    ]


def validate_promotion_order(user, attrs):
    """Из данных POST /billing/orders/ — объявление и сумма; 400 с кодом, если нельзя."""
    from apps.catalog.models import Item

    kind = attrs.get('promotion')
    if not kind:
        raise BillingError('PROMOTION_REQUIRED', 'Выберите вид продвижения: top или vip.')
    item = Item.objects.filter(pk=attrs.get('listing'), owner=user).first()
    if item is None:
        raise BillingError('LISTING_NOT_FOUND', 'Объявление не найдено.')
    if item.status != Item.STATUS_APPROVED:
        raise BillingError('LISTING_NOT_PUBLISHED', 'Продвигать можно только опубликованное объявление.')
    return {'item': item, 'amount': promotion_price(kind)}


def apply_promotion_order(order):
    """Оплата прошла: продлить продвижение объявления (под блокировкой строки)."""
    if order.item_id is None:
        order.needs_attention = 'Объявление удалено — продвижение не применено'
        order.save(update_fields=['needs_attention'])
        return
    item, ends_at = extend_promotion(order.item_id, order.promotion, promotion_days(order.promotion), order=order)
    _notify(
        order.user, 'Продвижение оплачено',
        f'{order.get_promotion_display()} для «{item.title}» действует до '
        f'{timezone.localtime(ends_at):%d.%m.%Y %H:%M}.',
    )


@transaction.atomic
def extend_promotion(item_id, kind, days, *, order=None):
    """Продлить продвижение от текущего окончания (или от сейчас). Для оплаты и для выдачи сотрудником."""
    from apps.catalog.models import Item

    item = Item.objects.select_for_update().get(pk=item_id)
    field = FIELD[kind]
    now = timezone.now()
    current = getattr(item, field)
    starts_at = current if current and current > now else now
    ends_at = starts_at + timedelta(days=days)
    setattr(item, field, ends_at)
    item.save(update_fields=[field, 'updated_at'])
    Promotion.objects.create(item=item, kind=kind, starts_at=starts_at, ends_at=ends_at, order=order)
    return item, ends_at


@transaction.atomic
def stop_promotion(item_id, kind):
    """Снять продвижение сейчас. True — было действующее."""
    from apps.catalog.models import Item

    item = Item.objects.select_for_update().get(pk=item_id)
    field = FIELD[kind]
    now = timezone.now()
    current = getattr(item, field)
    if not current or current <= now:
        return False
    setattr(item, field, now)
    item.save(update_fields=[field, 'updated_at'])
    Promotion.objects.filter(item=item, kind=kind, ends_at__gt=now).update(ends_at=now)
    return True

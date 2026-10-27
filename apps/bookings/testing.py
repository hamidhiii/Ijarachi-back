"""Фабрики для тестов сделок (не тест-модуль: имя не начинается с test)."""
import itertools
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model

from apps.bookings.models import Booking
from apps.catalog.models import Category, Item
from apps.payments.models import Payment

_phones = itertools.count(1)


def make_user(**extra):
    return get_user_model().objects.create_user(phone=f'+99890{next(_phones):07d}', **extra)


def make_item(owner, price=Decimal('100000'), deposit=Decimal('50000')):
    category, _ = Category.objects.get_or_create(slug='test-block1', defaults={'name': 'Test'})
    return Item.objects.create(
        owner=owner,
        category=category,
        title='Свадебные стулья',
        description='Набор',
        price_per_day=price,
        deposit=deposit,
        condition=Item.CONDITION_GOOD,
        status=Item.STATUS_APPROVED,
        address='Ташкент',
        city='Ташкент',
    )


def make_booking(item, renter, start=date(2030, 6, 10), end=date(2030, 6, 12), status=Booking.STATUS_DRAFT, **extra):
    days = (end - start).days + 1
    rent = item.price_per_day * days
    commission = (rent * Decimal('0.10')).quantize(Decimal('1'))
    total = rent + commission + item.deposit
    fields = dict(
        item=item,
        renter=renter,
        start_date=start,
        end_date=end,
        price_per_day=item.price_per_day,
        deposit_amount=item.deposit,
        commission_amount=commission,
        total_price=total,
        escrow_amount=total,
        deposit_status=Booking.DEPOSIT_PENDING if item.deposit > 0 else Booking.DEPOSIT_NONE,
        status=status,
    )
    fields.update(extra)
    return Booking.objects.create(**fields)


def make_paid_booking(item, renter, **kwargs):
    """Сделка, оплаченная онлайн: платёж paid, залог удержан."""
    kwargs.setdefault('status', Booking.STATUS_PAID)
    booking = make_booking(
        item, renter,
        escrow_status=Booking.ESCROW_HELD,
        deposit_status=Booking.DEPOSIT_HELD if item.deposit > 0 else Booking.DEPOSIT_NONE,
        **kwargs,
    )
    Payment.objects.create(
        booking=booking, provider=Payment.PROVIDER_STUB,
        amount=booking.total_price * 100, status=Payment.STATUS_PAID,
    )
    return booking

"""
Занятость дат объявления.

Раньше занятость хранилась одним списком ItemAvailability.blocked_dates на всё
объявление: бронь дописывала туда свои даты, отмена — вычёркивала диапазон.
Список не знал, чьи это даты, поэтому отмена черновика или просроченной заявки
вычёркивала и даты чужой оплаченной брони на те же дни, а PATCH календаря
владельцем затирал их целиком.

Теперь даты занимает сама бронь, пока она в одном из OCCUPYING_STATUSES:
отмена или истечение просто выводят её из этих статусов и освобождают ровно
её дни. В ItemAvailability.blocked_dates остаются только дни, которые владелец
закрыл вручную.

Гонку двух одновременных броней на одни даты разводит lock_item: проверка
пересечения и перевод брони в занимающий статус идут в одной транзакции под
select_for_update по строке объявления.
"""
from datetime import timedelta

from django.utils import timezone

from apps.catalog.models import Item, ItemAvailability

from .models import Booking

# pending_payment — даты держатся, пока идёт оплата (или владелец решает по
# наличным), иначе двое одновременно дойдут до оплаты одних и тех же дней.
# Черновик даты не занимает: это ещё не заявка, а расчёт цены.
OCCUPYING_STATUSES = (
    Booking.STATUS_PENDING_PAYMENT,
    Booking.STATUS_PAID,
    Booking.STATUS_IN_PROGRESS,
)


def lock_item(item_id) -> Item:
    """Блокирует строку объявления до конца транзакции (вызывать внутри atomic)."""
    return Item.objects.select_for_update().get(pk=item_id)


def overlapping_bookings(item, start, end, exclude_booking=None):
    qs = Booking.objects.filter(
        item=item,
        status__in=OCCUPYING_STATUSES,
        start_date__lte=end,
        end_date__gte=start,
    )
    if exclude_booking is not None:
        qs = qs.exclude(pk=exclude_booking.pk)
    return qs


def manual_blocked_dates(item) -> list[str]:
    try:
        return list(item.availability.blocked_dates)
    except ItemAvailability.DoesNotExist:
        return []


def is_range_free(item, start, end, exclude_booking=None) -> bool:
    if overlapping_bookings(item, start, end, exclude_booking).exists():
        return False
    # Даты в ISO сравниваются как строки — без перебора дней диапазона.
    lo, hi = start.isoformat(), end.isoformat()
    return not any(lo <= day <= hi for day in manual_blocked_dates(item))


def _days(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def booked_dates(item) -> list[str]:
    """Дни, занятые бронями, начиная с сегодняшнего (прошлое клиенту не нужно)."""
    today = timezone.localdate()
    days = set()
    ranges = Booking.objects.filter(
        item=item, status__in=OCCUPYING_STATUSES, end_date__gte=today,
    ).values_list('start_date', 'end_date')
    for start, end in ranges:
        days.update(day.isoformat() for day in _days(max(start, today), end))
    return sorted(days)


def blocked_dates(item) -> list[str]:
    """Всё, что нельзя забронировать: ручные блокировки владельца плюс брони."""
    return sorted(set(manual_blocked_dates(item)) | set(booked_dates(item)))

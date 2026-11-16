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

С 16.11.2026 объявление описывает модель вещи с количеством (Item.quantity), и
дни занимают не только сделки, но и брони владельца из CRM (apps.crm.Reservation,
со своим количеством). День занят полностью, когда занятых единиц не меньше
quantity; сделка занимает одну единицу. При quantity=1 всё как прежде.
"""
from collections import defaultdict
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


def _days(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def units_by_day(item, start, end, exclude_booking=None, exclude_reservation=None) -> dict:
    """Сколько единиц объявления занято в каждый день диапазона (только занятые дни)."""
    from apps.crm.models import Reservation

    counts = defaultdict(int)
    for b_start, b_end in overlapping_bookings(item, start, end, exclude_booking).values_list('start_date', 'end_date'):
        for day in _days(max(b_start, start), min(b_end, end)):
            counts[day] += 1
    reservations = Reservation.objects.filter(
        item=item, status__in=Reservation.OCCUPYING_STATUSES, start_date__lte=end, end_date__gte=start,
    )
    if exclude_reservation is not None:
        reservations = reservations.exclude(pk=exclude_reservation.pk)
    for r_start, r_end, quantity in reservations.values_list('start_date', 'end_date', 'quantity'):
        for day in _days(max(r_start, start), min(r_end, end)):
            counts[day] += quantity
    return counts


def manually_blocked_in(item, start, end) -> bool:
    # Даты в ISO сравниваются как строки — без перебора дней диапазона.
    lo, hi = start.isoformat(), end.isoformat()
    return any(lo <= day <= hi for day in manual_blocked_dates(item))


def is_range_free(item, start, end, exclude_booking=None, units=1, exclude_reservation=None) -> bool:
    """Свободно ли `units` единиц на каждый день диапазона (вызывать под lock_item)."""
    if manually_blocked_in(item, start, end):
        return False
    counts = units_by_day(item, start, end, exclude_booking, exclude_reservation)
    return all(counts.get(day, 0) + units <= item.quantity for day in _days(start, end))


def booked_dates(item) -> list[str]:
    """Дни, занятые полностью (свободных единиц нет), начиная с сегодняшнего."""
    from apps.crm.models import Reservation

    today = timezone.localdate()
    last = Booking.objects.filter(item=item, status__in=OCCUPYING_STATUSES, end_date__gte=today).order_by('-end_date')
    last_reservation = Reservation.objects.filter(
        item=item, status__in=Reservation.OCCUPYING_STATUSES, end_date__gte=today,
    ).order_by('-end_date')
    ends = [qs.values_list('end_date', flat=True).first() for qs in (last, last_reservation)]
    ends = [end for end in ends if end]
    if not ends:
        return []
    counts = units_by_day(item, today, max(ends))
    return sorted(day.isoformat() for day, used in counts.items() if used >= item.quantity)


def blocked_dates(item) -> list[str]:
    """Всё, что нельзя забронировать: ручные блокировки владельца плюс занятые полностью дни."""
    return sorted(set(manual_blocked_dates(item)) | set(booked_dates(item)))

"""Брони кабинета: создание и изменение с проверкой остатков под блокировкой объявления."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status
from rest_framework.exceptions import APIException

from apps.bookings.availability import _days, lock_item, manually_blocked_in, units_by_day

from .models import Client, Reservation


class CrmError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'CRM_ERROR'

    def __init__(self, code, detail, http_status=None, **extra):
        super().__init__()
        if http_status:
            self.status_code = http_status
        self.detail = {'code': code, 'detail': detail, **extra}


def free_units(item, start, end, exclude_reservation=None):
    """Сколько единиц свободно на весь диапазон (минимум по дням); 0 — день закрыт вручную."""
    if manually_blocked_in(item, start, end):
        return 0
    counts = units_by_day(item, start, end, exclude_reservation=exclude_reservation)
    busiest = max((counts.get(day, 0) for day in _days(start, end)), default=0)
    return max(item.quantity - busiest, 0)


def client_for(account, client=None, name='', phone=''):
    """Клиент брони: выбранный из базы или новый/найденный по телефону."""
    if client is not None:
        return client
    phone = (phone or '').strip()
    name = (name or '').strip()
    if not phone and not name:
        return None
    if phone:
        found = Client.objects.filter(owner=account, phone=phone).first()
        if found:
            return found
    rentoo_user = get_user_model().objects.filter(phone=phone).first() if phone else None
    return Client.objects.create(owner=account, name=name or phone, phone=phone, user=rentoo_user)


def check_dates(start, end):
    if end < start:
        raise CrmError('INVALID_DATES', 'Дата возврата раньше даты выдачи.')
    if (end - start).days + 1 > settings.BOOKING_MAX_DAYS:
        raise CrmError('INVALID_DATES', f'Бронь не может быть длиннее {settings.BOOKING_MAX_DAYS} дней.')


@transaction.atomic
def save_reservation(account, data, *, instance=None, actor=None):
    """
    Создаёт или меняет бронь. Объявление под select_for_update: две брони на
    последние свободные единицы не проходят обе (как у сделок, блок 1).
    """
    item = data.get('item') or instance.item
    item = lock_item(item.pk)
    start = data.get('start_date', instance.start_date if instance else None)
    end = data.get('end_date', instance.end_date if instance else None)
    quantity = data.get('quantity', instance.quantity if instance else 1)
    new_status = data.get('status', instance.status if instance else Reservation.STATUS_BOOKED)
    check_dates(start, end)

    if instance is not None and new_status != instance.status:
        if new_status not in Reservation.TRANSITIONS[instance.status]:
            raise CrmError(
                'INVALID_STATUS',
                f'Нельзя перевести бронь из «{instance.get_status_display()}» в «{dict(Reservation.STATUS_CHOICES)[new_status]}».',
            )

    if new_status in Reservation.OCCUPYING_STATUSES:
        if quantity > item.quantity:
            raise CrmError('NOT_ENOUGH_STOCK', f'В объявлении всего {item.quantity} шт.', status.HTTP_409_CONFLICT,
                            free=item.quantity, total=item.quantity, over_total=True)
        free = free_units(item, start, end, exclude_reservation=instance)
        if quantity > free:
            raise CrmError(
                'NOT_ENOUGH_STOCK',
                f'На эти даты свободно {free} шт. из {item.quantity}.',
                status.HTTP_409_CONFLICT, free=free, total=item.quantity,
            )

    client = client_for(account, data.get('client'), data.get('client_name', ''), data.get('client_phone', ''))
    fields = {
        'item': item, 'start_date': start, 'end_date': end, 'quantity': quantity, 'status': new_status,
    }
    for key in ('source', 'price', 'notes'):
        if key in data:
            fields[key] = data[key]
    if client is not None or 'client' in data:
        fields['client'] = client

    if instance is None:
        return Reservation.objects.create(owner=account, created_by=actor, **fields)
    if (instance.start_date, instance.end_date) != (start, end):
        # Даты сдвинули — напоминания должны прийти заново.
        fields['pickup_reminded_on'] = None
        fields['return_reminded_on'] = None
    for key, value in fields.items():
        setattr(instance, key, value)
    instance.save()
    return instance


def date_range(start, end, limit_days=92):
    if end < start:
        raise CrmError('INVALID_DATES', 'Конец периода раньше начала.')
    if (end - start).days + 1 > limit_days:
        raise CrmError('INVALID_DATES', f'Период не длиннее {limit_days} дней.')
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]

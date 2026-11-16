"""Выгрузка данных аккаунта в CSV или XLSX (тариф PRO)."""
import csv
import io

from django.http import HttpResponse
from django.utils import timezone

from apps.catalog.models import Item

from .models import Client, Reservation


def _listings(account):
    yield ['ID', 'Название', 'Статус', 'Количество', 'Цена за сутки', 'Залог', 'Точка', 'Город', 'Создано']
    for item in Item.objects.filter(owner=account).select_related('branch').order_by('pk'):
        yield [
            item.pk, item.title, item.get_status_display(), item.quantity, int(item.price_per_day),
            int(item.deposit), item.branch.name if item.branch else '', item.city,
            timezone.localtime(item.created_at).strftime('%d.%m.%Y'),
        ]


def _reservations(account):
    yield ['ID', 'Объявление', 'Количество', 'Выдача', 'Возврат', 'Статус', 'Источник', 'Клиент', 'Телефон', 'Сумма', 'Заметки']
    rows = Reservation.objects.filter(owner=account).select_related('item', 'client').order_by('start_date', 'pk')
    for r in rows:
        yield [
            r.pk, r.item.title, r.quantity, r.start_date.strftime('%d.%m.%Y'), r.end_date.strftime('%d.%m.%Y'),
            r.get_status_display(), r.get_source_display(), r.client.name if r.client else '',
            r.client.phone if r.client else '', int(r.price) if r.price is not None else '', r.notes,
        ]


def _clients(account):
    yield ['ID', 'Имя', 'Телефон', 'Заметки', 'Броней', 'Добавлен']
    for client in Client.objects.filter(owner=account).order_by('name', 'pk'):
        yield [
            client.pk, client.name, client.phone, client.notes,
            client.reservations.exclude(status=Reservation.STATUS_CANCELLED).count(),
            timezone.localtime(client.created_at).strftime('%d.%m.%Y'),
        ]


ENTITIES = {'listings': _listings, 'reservations': _reservations, 'clients': _clients}


def render(account, entity, fmt):
    rows = ENTITIES[entity](account)
    filename = f'rentoo-{entity}-{timezone.localdate():%Y-%m-%d}.{fmt}'
    if fmt == 'csv':
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for row in rows:
            writer.writerow(row)
        # BOM — чтобы Excel открыл кириллицу без ручного выбора кодировки.
        response = HttpResponse('﻿' + buffer.getvalue(), content_type='text/csv; charset=utf-8')
    else:
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = entity
        for row in rows:
            sheet.append(row)
        buffer = io.BytesIO()
        workbook.save(buffer)
        response = HttpResponse(
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

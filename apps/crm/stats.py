"""Статистика объявлений владельца: просмотры, показы номера, сообщения в чате."""
from datetime import timedelta

from django.db.models import Count, Q, Sum

from apps.catalog.models import Item, ListingDailyStat, PhoneReveal
from apps.chat.models import Message


def _messages(account, first, last):
    """Входящие сообщения (не от владельца) в диалогах по объявлениям аккаунта."""
    return Message.objects.filter(
        conversation__listing__owner=account,
        created_at__date__gte=first, created_at__date__lte=last,
    ).exclude(sender=account)


def listing_stats(account, first, last):
    items = Item.objects.filter(owner=account).exclude(status=Item.STATUS_REJECTED).order_by('title', 'pk')
    views = dict(
        ListingDailyStat.objects.filter(item__owner=account, date__gte=first, date__lte=last)
        .values('item').annotate(total=Sum('views')).values_list('item', 'total')
    )
    reveals = dict(
        PhoneReveal.objects.filter(
            item__owner=account, counted=True, created_at__date__gte=first, created_at__date__lte=last,
        ).values('item').annotate(total=Count('pk')).values_list('item', 'total')
    )
    messages = dict(
        _messages(account, first, last).values('conversation__listing')
        .annotate(total=Count('pk')).values_list('conversation__listing', 'total')
    )
    return [
        {
            'id': item.pk, 'title': item.title, 'status': item.status,
            'views': views.get(item.pk, 0),
            'phone_reveals': reveals.get(item.pk, 0),
            'chat_messages': messages.get(item.pk, 0),
        }
        for item in items
    ]


def monthly_totals(account, last_month_first, months=6):
    """Итоги аккаунта по месяцам, от старого к выбранному."""
    firsts = [last_month_first]
    for _ in range(months - 1):
        firsts.insert(0, (firsts[0] - timedelta(days=1)).replace(day=1))
    rows = []
    for first in firsts:
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        rows.append({
            'month': first.strftime('%Y-%m'),
            'views': ListingDailyStat.objects.filter(item__owner=account, date__gte=first, date__lte=last)
            .aggregate(total=Sum('views'))['total'] or 0,
            'phone_reveals': PhoneReveal.objects.filter(
                Q(item__owner=account), counted=True, created_at__date__gte=first, created_at__date__lte=last,
            ).count(),
            'chat_messages': _messages(account, first, last).count(),
        })
    return rows



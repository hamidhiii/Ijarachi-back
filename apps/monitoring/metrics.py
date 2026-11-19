"""
Цифры для монитора (monitor.rentoo.uz): всё, что мониторится, одним ответом.

overview(days, access) → KPI за период и за такой же период до него (дельта
считается на фронте), дневные ряды для графиков, разбивки для круговых
диаграмм и последние события. Деньги (выручка, оборот сделок, MRR) — только
тем, у кого в мониторе открыт раздел «Платежи».
"""
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from . import presence

User = get_user_model()


def _days(start, end):
    out, day = [], start
    while day <= end:
        out.append(day)
        day += timedelta(days=1)
    return out


def _daily(qs, field, start, end, value=None):
    """{дата: значение} по дням, пропуски — 0."""
    rows = (
        qs.filter(**{f'{field}__date__gte': start, f'{field}__date__lte': end})
        .annotate(day=TruncDate(field)).values('day')
        .annotate(v=value or Count('id')).values_list('day', 'v')
    )
    found = {day: int(v or 0) for day, v in rows}
    return [found.get(day, 0) for day in _days(start, end)]


def _count(qs, field, start, end):
    return qs.filter(**{f'{field}__date__gte': start, f'{field}__date__lte': end}).count()


def _sum(qs, field, amount, start, end):
    total = qs.filter(**{f'{field}__date__gte': start, f'{field}__date__lte': end}).aggregate(s=Sum(amount))['s']
    return int(total or 0)


def _kpi(key, label, value, prev=None, unit='', hint='', series=None, group='', invert=False):
    return {'key': key, 'label': label, 'value': value, 'prev': prev, 'unit': unit, 'hint': hint,
            'series': series, 'group': group, 'invert': invert}


def _breakdown(rows, labels):
    found = {code: total for code, total in rows}
    return [{'key': code, 'label': label, 'value': found.get(code, 0)} for code, label in labels if found.get(code, 0)]


def overview(days, access):
    from apps.billing.models import BillingOrder, Plan, Subscription
    from apps.bookings.models import Booking
    from apps.catalog.models import Item, PhoneReveal, Report
    from apps.chat.models import Conversation, Message
    from apps.crm.models import Reservation
    from apps.payments.models import Payment
    from apps.users.models import PassportDocument, Profile

    money = access.level('payments') in ('view', 'edit')
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    now = timezone.now()
    paid_deal = [Booking.STATUS_PAID, Booking.STATUS_IN_PROGRESS, Booking.STATUS_RETURNED,
                 Booking.STATUS_COMPLETED, Booking.STATUS_DISPUTED]

    users = User.objects.filter(is_active=True)
    items = Item.objects.all()
    deals = Booking.objects.exclude(status=Booking.STATUS_DRAFT)
    messages = Message.objects.all()
    reservations = Reservation.objects.all()
    orders = BillingOrder.objects.filter(status=BillingOrder.STATUS_PAID).exclude(provider=BillingOrder.PROVIDER_STUB)

    def both(qs, field):
        return _count(qs, field, start, today), _count(qs, field, prev_start, prev_end)

    signups, signups_prev = both(users, 'date_joined')
    new_items, new_items_prev = both(items.exclude(status=Item.STATUS_CRM), 'created_at')
    new_deals, new_deals_prev = both(deals, 'created_at')
    msgs, msgs_prev = both(messages, 'created_at')
    res, res_prev = both(reservations, 'created_at')
    reveals, reveals_prev = both(PhoneReveal.objects.filter(counted=True), 'created_at')
    visitors = presence.unique_over('hll:v', start, today)
    visitors_prev = presence.unique_over('hll:v', prev_start, prev_end)
    active_users = presence.unique_over('hll:u', start, today)
    active_users_prev = presence.unique_over('hll:u', prev_start, prev_end)

    paying_now = (Subscription.objects.filter(ends_at__gt=now).exclude(plan__code=Plan.FREE)
                  .values('plan__code').annotate(n=Count('id')))
    paying = {row['plan__code']: row['n'] for row in paying_now}
    plans = list(Plan.objects.order_by('rank'))

    daily_visitors = presence.daily_counts('hll:v', start, today)
    daily_active = presence.daily_counts('hll:u', start, today)
    series = {
        'dates': [day.isoformat() for day in _days(start, today)],
        'visitors': [daily_visitors[d] for d in _days(start, today)],
        'active_users': [daily_active[d] for d in _days(start, today)],
        'signups': _daily(users, 'date_joined', start, today),
        'listings': _daily(items.exclude(status=Item.STATUS_CRM), 'created_at', start, today),
        'deals': _daily(deals, 'created_at', start, today),
        'messages': _daily(messages, 'created_at', start, today),
        'reservations': _daily(reservations, 'created_at', start, today),
        'reveals': _daily(PhoneReveal.objects.filter(counted=True), 'created_at', start, today),
    }

    kpis = [
        _kpi('visitors', 'Уникальные посетители', visitors, visitors_prev, series=series['visitors'], group='audience',
             hint='Разные устройства за период'),
        _kpi('active_users', 'Активные пользователи', active_users, active_users_prev, series=series['active_users'],
             group='audience', hint='Вошедшие, открывавшие сайт'),
        _kpi('signups', 'Регистрации', signups, signups_prev, series=series['signups'], group='audience'),
        _kpi('users_total', 'Всего пользователей', users.count(), group='audience'),
        _kpi('new_listings', 'Новые объявления', new_items, new_items_prev, series=series['listings'], group='market'),
        _kpi('live_listings', 'Опубликовано сейчас', items.filter(status=Item.STATUS_APPROVED).count(), group='market'),
        _kpi('moderation', 'На модерации', items.filter(status=Item.STATUS_PENDING).count(), group='market',
             invert=True),
        _kpi('reveals', 'Показы номера', reveals, reveals_prev, series=series['reveals'], group='market'),
        _kpi('messages', 'Сообщения в чатах', msgs, msgs_prev, series=series['messages'], group='market'),
        _kpi('deals', 'Новые сделки', new_deals, new_deals_prev, series=series['deals'], group='deals'),
        _kpi('reservations', 'Брони в CRM', res, res_prev, series=series['reservations'], group='crm'),
        _kpi('crm_products', 'Товары только в CRM', items.filter(status=Item.STATUS_CRM).count(), group='crm'),
        _kpi('paying', 'Платящие сейчас', sum(paying.values()), group='billing'),
    ]

    if money:
        series['revenue'] = _daily(orders, 'paid_at', start, today, Sum('amount'))
        series['gmv'] = _daily(deals.filter(status__in=paid_deal), 'created_at', start, today, Sum('total_price'))
        revenue = _sum(orders, 'paid_at', 'amount', start, today)
        revenue_prev = _sum(orders, 'paid_at', 'amount', prev_start, prev_end)
        gmv = _sum(deals.filter(status__in=paid_deal), 'created_at', 'total_price', start, today)
        gmv_prev = _sum(deals.filter(status__in=paid_deal), 'created_at', 'total_price', prev_start, prev_end)
        mrr = sum(int(plan.price) * paying.get(plan.code, 0) for plan in plans)
        commission = _sum(deals.filter(status__in=paid_deal), 'created_at', 'commission_amount', start, today)
        kpis += [
            _kpi('revenue', 'Выручка (тарифы и реклама)', revenue, revenue_prev, 'сум', series=series['revenue'],
                 group='billing'),
            _kpi('mrr', 'MRR', mrr, unit='сум', group='billing', hint='Платящие × цена тарифа'),
            _kpi('gmv', 'Оборот сделок', gmv, gmv_prev, 'сум', series=series['gmv'], group='deals'),
            _kpi('commission', 'Комиссия с сделок', commission, unit='сум', group='deals'),
            _kpi('escrow', 'В эскроу сейчас',
                 int(Booking.objects.filter(escrow_status=Booking.ESCROW_HELD).aggregate(s=Sum('escrow_amount'))['s'] or 0),
                 unit='сум', group='deals'),
        ]

    kpis += [
        _kpi('disputes', 'Открытые споры', deals.filter(status=Booking.STATUS_DISPUTED).count(), group='risk',
             invert=True),
        _kpi('kyc_pending', 'KYC ждут проверки',
             PassportDocument.objects.filter(status=PassportDocument.STATUS_PENDING).count(), group='risk', invert=True),
        _kpi('reports', 'Жалобы без ответа', Report.objects.filter(status=Report.STATUS_NEW).count(), group='risk',
             invert=True),
        _kpi('payments_failed', 'Сбои оплаты', _count(Payment.objects.filter(status=Payment.STATUS_FAILED),
                                                      'created_at', start, today), group='risk', invert=True),
    ]

    breakdowns = {
        'listings_by_status': _breakdown(items.values_list('status').annotate(n=Count('id')), Item.STATUS_CHOICES),
        'deals_by_status': _breakdown(deals.values_list('status').annotate(n=Count('id')), Booking.STATUS_CHOICES),
        'users_by_type': _breakdown(Profile.objects.values_list('account_type').annotate(n=Count('id')),
                                    Profile.ACCOUNT_TYPE_CHOICES),
        'plans': [{'key': 'free', 'label': 'FREE', 'value': max(users.count() - sum(paying.values()), 0)}] + [
            {'key': plan.code, 'label': plan.name, 'value': paying.get(plan.code, 0)}
            for plan in plans if plan.is_paid
        ],
        'top_categories': [
            {'key': str(row['category__id']), 'label': row['category__name'] or '—', 'value': row['n']}
            for row in items.filter(status=Item.STATUS_APPROVED).values('category__id', 'category__name')
            .annotate(n=Count('id')).order_by('-n')[:8]
        ],
        'conversations': Conversation.objects.count(),
    }

    recent = {
        'users': [
            {'id': u.pk, 'phone': u.phone, 'name': getattr(getattr(u, 'profile', None), 'full_name', '') or '',
             'at': u.date_joined.isoformat()}
            for u in users.select_related('profile').order_by('-date_joined')[:8]
        ],
        'listings': [
            {'id': i.pk, 'title': i.title, 'status': i.status, 'status_label': i.get_status_display(),
             'price': int(i.price_per_day), 'owner': i.owner.phone, 'at': i.created_at.isoformat()}
            for i in items.exclude(status=Item.STATUS_CRM).select_related('owner').order_by('-created_at')[:8]
        ],
        'deals': [
            {'id': b.pk, 'title': b.item.title if b.item_id else '—', 'status': b.status,
             'status_label': b.get_status_display(), 'total': int(b.total_price) if money else None,
             'at': b.created_at.isoformat()}
            for b in deals.select_related('item').order_by('-created_at')[:8]
        ],
    }

    return {
        'period': {'days': days, 'from': start.isoformat(), 'to': today.isoformat(),
                   'prev_from': prev_start.isoformat(), 'prev_to': prev_end.isoformat()},
        'money': money,
        'kpis': kpis,
        'series': series,
        'breakdowns': breakdowns,
        'recent': recent,
    }


def auth_funnel(days):
    """Вход и регистрация за `days` дней: воронка, сбои, кто застрял. Для страницы и API."""
    from .models import AuthEvent

    PAGE_SIZE = 50
    since = timezone.now() - timedelta(days=days)
    rows = list(
        AuthEvent.objects.filter(created_at__gte=since)
        .order_by('created_at')
        .values_list('event', 'phone', 'visitor_id', 'detail', 'created_at')
    )

    by_event = {}
    phones_by_event = {}
    visitors_by_event = {}
    for event, phone, visitor, _detail, _at in rows:
        by_event[event] = by_event.get(event, 0) + 1
        if phone:
            phones_by_event.setdefault(event, set()).add(phone)
        if visitor:
            visitors_by_event.setdefault(event, set()).add(visitor)

    def phones(*events_):
        return set().union(*(phones_by_event.get(e, set()) for e in events_))

    done_phones = phones(AuthEvent.LOGIN_OK, AuthEvent.REGISTER_OK)
    code_not_entered = phones(AuthEvent.OTP_SENT) - done_phones
    never_got_code = (
        phones(AuthEvent.OTP_TELEGRAM_REQUIRED, AuthEvent.OTP_SEND_FAILED, AuthEvent.OTP_COOLDOWN)
        - phones(AuthEvent.OTP_SENT) - done_phones
    )

    # «Зашли и ушли»: посетитель есть, а ни одного шага входа от него не было.
    acted = set().union(*(
        visitors_by_event.get(e, set()) for e in AuthEvent.OTP_ACTIVITY
    ))
    bounced = visitors_by_event.get(AuthEvent.VISIT, set()) - acted

    last_event = {}
    for event, phone, _visitor, detail, at in rows:
        if phone:
            last_event[phone] = (event, detail, at)

    def stuck_rows(phone_set):
        out = []
        for phone in phone_set:
            event, detail, at = last_event.get(phone, ('', '', None))
            out.append({'phone': phone, 'event': dict(AuthEvent.EVENT_CHOICES).get(event, event),
                        'detail': detail, 'at': at})
        return sorted(out, key=lambda r: r['at'] or timezone.now(), reverse=True)[:PAGE_SIZE]

    funnel = [
        ('Зашли на сайт', len(visitors_by_event.get(AuthEvent.VISIT, ()))),
        ('Открыли форму входа', len(visitors_by_event.get(AuthEvent.AUTH_OPENED, ()))),
        ('Запросили код', len(phones(AuthEvent.OTP_SENT, AuthEvent.OTP_TELEGRAM_REQUIRED,
                                     AuthEvent.OTP_COOLDOWN, AuthEvent.OTP_SEND_FAILED))),
        ('Получили код', len(phones(AuthEvent.OTP_SENT))),
        ('Вошли или зарегистрировались', len(done_phones)),
    ]

    failure_rows = [
        {'label': label, 'total': by_event.get(code, 0), 'phones': len(phones_by_event.get(code, ()))}
        for code, label in AuthEvent.EVENT_CHOICES if code in AuthEvent.FAILURE_EVENTS
    ]

    recent_failures = [
        {'label': dict(AuthEvent.EVENT_CHOICES).get(event, event), 'phone': phone, 'detail': detail, 'at': at}
        for event, phone, _visitor, detail, at in reversed(rows)
        if event in AuthEvent.FAILURE_EVENTS
    ][:PAGE_SIZE]

    return {
        'days': days,
        'funnel': funnel,
        'registered': by_event.get(AuthEvent.REGISTER_OK, 0),
        'logged_in': by_event.get(AuthEvent.LOGIN_OK, 0),
        'users_joined': User.objects.filter(date_joined__gte=since).count(),
        'bounced_total': len(bounced),
        'bounced_known': bool(visitors_by_event.get(AuthEvent.VISIT)),
        'code_not_entered': stuck_rows(code_not_entered),
        'code_not_entered_total': len(code_not_entered),
        'never_got_code': stuck_rows(never_got_code),
        'never_got_code_total': len(never_got_code),
        'failure_rows': failure_rows,
        'recent_failures': recent_failures,
        'has_events': bool(rows),
    }

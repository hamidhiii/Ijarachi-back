"""
Диагностика: где сделки перестали двигаться и что требует ручного решения.
Всё считается прямо из БД на каждый запрос — отдельного хранилища состояния нет.
"""
import operator
from dataclasses import dataclass, field
from datetime import timedelta
from functools import reduce

from django.conf import settings
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

# Сколько строк показываем в одном блоке ошибок; общее число отдаём отдельно,
# чтобы урезанный список не читался как «это всё».
ISSUE_LIMIT = 50


@dataclass
class StuckDeal:
    booking: object
    reason: str
    since: object
    age_hours: int


@dataclass
class Issue:
    label: str
    detail: str = ''
    url: str = ''


@dataclass
class CheckResult:
    code: str
    title: str
    hint: str
    severity: str  # error — деньги или данные разъехались, warning — просто висит
    total: int = 0
    issues: list = field(default_factory=list)

    @property
    def truncated(self):
        return self.total > len(self.issues)


def _deal_url(booking_id):
    return reverse('monitor:deal_detail', args=[booking_id])


def stuck_deals():
    """Сделки, застрявшие в статусе: по времени в статусе или по датам аренды."""
    from apps.bookings.models import Booking

    now = timezone.now()
    today = timezone.localdate()
    hours = settings.MONITOR_STUCK_HOURS

    # Статусы, из которых сделка должна уходить сама, и предел ожидания.
    time_rules = {
        Booking.STATUS_DRAFT: 'Черновик так и не стал заказом',
        Booking.STATUS_PENDING_PAYMENT: 'Ждёт оплату дольше обычного',
        Booking.STATUS_RETURNED: 'Возврат подтверждён, но сделка не закрыта',
        Booking.STATUS_DISPUTED: 'Спор никто не разобрал',
    }

    conditions = [
        Q(status=status, updated_at__lt=now - timedelta(hours=hours[status]))
        for status in time_rules
        if hours.get(status)
    ]
    # Эти два статуса ограничены не таймером, а датами самой аренды.
    conditions.append(Q(status=Booking.STATUS_PAID, start_date__lt=today))
    conditions.append(Q(status=Booking.STATUS_IN_PROGRESS, end_date__lt=today))

    queryset = (
        Booking.objects
        .filter(reduce(operator.or_, conditions))
        .select_related('item', 'item__owner', 'renter')
        .order_by('updated_at')
    )

    result = []
    for booking in queryset:
        if booking.status == Booking.STATUS_PAID:
            reason = f'Оплачено, но аренда не началась — старт был {booking.start_date:%d.%m.%Y}'
        elif booking.status == Booking.STATUS_IN_PROGRESS:
            reason = f'Аренда закончилась {booking.end_date:%d.%m.%Y}, возврат не отмечен'
        else:
            reason = time_rules[booking.status]
        result.append(StuckDeal(
            booking=booking,
            reason=reason,
            since=booking.updated_at,
            age_hours=int((now - booking.updated_at).total_seconds() // 3600),
        ))
    return result


def _build(code, title, hint, severity, queryset, label, detail=None, url=None):
    total = queryset.count()
    issues = [
        Issue(
            label=label(obj),
            detail=detail(obj) if detail else '',
            url=url(obj) if url else '',
        )
        for obj in queryset[:ISSUE_LIMIT]
    ]
    return CheckResult(code=code, title=title, hint=hint, severity=severity, total=total, issues=issues)


def failed_payments():
    from apps.payments.models import Payment

    since = timezone.now() - timedelta(days=7)
    queryset = (
        Payment.objects
        .filter(status=Payment.STATUS_FAILED, created_at__gte=since)
        .select_related('booking')
        .order_by('-created_at')
    )
    return _build(
        'payments_failed',
        'Платежи с ошибкой за 7 дней',
        'Провайдер вернул отказ. Сырой ответ вебхука виден в карточке сделки.',
        'error',
        queryset,
        label=lambda p: f'Платёж #{p.pk} ({p.get_provider_display()}) по сделке #{p.booking_id}',
        detail=lambda p: f'{p.amount} тийин, {p.created_at:%d.%m.%Y %H:%M}',
        url=lambda p: _deal_url(p.booking_id),
    )


def hanging_payments():
    from apps.payments.models import Payment

    limit = timezone.now() - timedelta(hours=settings.MONITOR_PAYMENT_PENDING_HOURS)
    queryset = (
        Payment.objects
        .filter(status=Payment.STATUS_PENDING, created_at__lt=limit)
        .select_related('booking')
        .order_by('created_at')
    )
    return _build(
        'payments_pending',
        'Платежи зависли в «Ожидает»',
        'Вебхук от провайдера не пришёл или не был обработан — деньги в подвешенном состоянии.',
        'error',
        queryset,
        label=lambda p: f'Платёж #{p.pk} ({p.get_provider_display()}) по сделке #{p.booking_id}',
        detail=lambda p: f'создан {p.created_at:%d.%m.%Y %H:%M}',
        url=lambda p: _deal_url(p.booking_id),
    )


def payment_status_mismatch():
    """Платёж прошёл, а сделка этого не заметила — расхождение после вебхука."""
    from apps.bookings.models import Booking
    from apps.payments.models import Payment

    queryset = (
        Booking.objects
        .filter(
            payments__status__in=[Payment.STATUS_PAID, Payment.STATUS_COMPLETED],
            status__in=[Booking.STATUS_DRAFT, Booking.STATUS_PENDING_PAYMENT, Booking.STATUS_CANCELLED],
        )
        .select_related('item')
        .distinct()
        .order_by('-updated_at')
    )
    return _build(
        'payment_mismatch',
        'Оплата прошла, а сделка не перешла в оплаченные',
        'Платёж в статусе paid или completed, но бронь всё ещё в черновике, ждёт оплату или отменена.',
        'error',
        queryset,
        label=lambda b: f'Сделка #{b.pk} — {b.item.title}',
        detail=lambda b: f'статус сделки: {b.get_status_display()}',
        url=lambda b: _deal_url(b.pk),
    )


def escrow_mismatch():
    """Статус сделки и состояние эскроу разъехались."""
    from apps.bookings.models import Booking

    active_statuses = [Booking.STATUS_PAID, Booking.STATUS_IN_PROGRESS, Booking.STATUS_RETURNED]
    queryset = (
        Booking.objects
        .filter(
            Q(
                status__in=active_statuses,
                escrow_status__in=[Booking.ESCROW_PENDING, Booking.ESCROW_RELEASED, Booking.ESCROW_REFUNDED],
            )
            | Q(
                status=Booking.STATUS_COMPLETED,
                escrow_status__in=[Booking.ESCROW_PENDING, Booking.ESCROW_HELD, Booking.ESCROW_FROZEN],
            )
        )
        .select_related('item')
        .order_by('-updated_at')
    )
    return _build(
        'escrow_mismatch',
        'Эскроу не соответствует статусу сделки',
        'Аренда идёт, а деньги уже выплачены или ещё не удержаны; либо сделка закрыта, а деньги висят.',
        'error',
        queryset,
        label=lambda b: f'Сделка #{b.pk} — {b.item.title}',
        detail=lambda b: f'{b.get_status_display()} / эскроу: {b.get_escrow_status_display()}',
        url=lambda b: _deal_url(b.pk),
    )


def old_disputes():
    from apps.bookings.models import Booking

    limit = timezone.now() - timedelta(hours=settings.MONITOR_STUCK_HOURS[Booking.STATUS_DISPUTED])
    queryset = (
        Booking.objects
        .filter(status=Booking.STATUS_DISPUTED, updated_at__lt=limit)
        .select_related('item')
        .order_by('updated_at')
    )
    return _build(
        'disputes_old',
        'Споры без решения',
        'Пока спор открыт, деньги по сделке заморожены.',
        'warning',
        queryset,
        label=lambda b: f'Сделка #{b.pk} — {b.item.title}',
        detail=lambda b: (b.dispute_reason or 'причина не указана')[:120],
        url=lambda b: _deal_url(b.pk),
    )


def kyc_waiting():
    from apps.users.models import PassportDocument

    limit = timezone.now() - timedelta(hours=settings.MONITOR_KYC_PENDING_HOURS)
    queryset = (
        PassportDocument.objects
        .filter(status=PassportDocument.STATUS_PENDING, submitted_at__lt=limit)
        .select_related('user')
        .order_by('submitted_at')
    )
    return _build(
        'kyc_pending',
        'Документы KYC ждут проверки',
        'Пока документ не подтверждён, пользователь не выйдет на первую сделку.',
        'warning',
        queryset,
        label=lambda d: f'{d.user.phone} — {d.get_document_type_display()}',
        detail=lambda d: f'подан {d.submitted_at:%d.%m.%Y %H:%M}',
        url=lambda d: reverse('monitor:kyc'),
    )


def kyc_face_failed():
    from apps.users.models import FaceVerification

    queryset = (
        FaceVerification.objects
        .filter(status=FaceVerification.STATUS_FAILED)
        .select_related('user')
        .order_by('-submitted_at')
    )
    return _build(
        'kyc_face_failed',
        'Сверка лица не пройдена',
        'Автоматика отказала — нужно решение человека.',
        'warning',
        queryset,
        label=lambda f: f'{f.user.phone}',
        detail=lambda f: (f.fail_reason or 'причина не указана')[:120],
        url=lambda f: reverse('monitor:kyc'),
    )


ALL_CHECKS = (
    payment_status_mismatch,
    escrow_mismatch,
    hanging_payments,
    failed_payments,
    old_disputes,
    kyc_waiting,
    kyc_face_failed,
)


def run_checks():
    """Все проверки разом; пустые не показываем."""
    return [result for result in (check() for check in ALL_CHECKS) if result.total]

"""
Расчёт по сделке: выплата владельцу за аренду, возврат или удержание залога.

Выплата владельцу — аренда минус комиссия, зафиксированная в сделке
(Booking.commission_amount, модель B: удерживается из выплаты).

Залог и аренда разведены. При завершении сделки аренда (за вычетом комиссии)
уходит владельцу, а залог — арендатору целиком. Если был спор, сотрудник
решает, какую часть залога удержать в пользу владельца (resolve_dispute);
остаток возвращается арендатору. Каждое движение залога пишется в
DepositOperation, каждое начисление — в WalletTransaction.

Повторный или параллельный расчёт одной сделки ничего не начисляет второй
раз: строка сделки берётся под select_for_update, и после первого расчёта у
неё escrow_status=released. Сверху это страхует уникальное ограничение
WalletTransaction (одно начисление каждого типа на сделку).
"""
import logging
from decimal import Decimal

from django.db import transaction

from .models import Booking, DepositOperation

logger = logging.getLogger('apps.bookings')


class SettlementError(Exception):
    pass


def refund_deposit_on_cancel(booking, comment='', actor=None):
    """
    Сделку отменили. Удержанный залог возвращается вместе со всей суммой оплаты
    (через провайдера, см. возврат в Transaction), здесь — только его история.
    Неоплаченный залог просто перестаёт ожидаться.
    """
    if booking.deposit_status == Booking.DEPOSIT_HELD:
        DepositOperation.objects.create(
            booking=booking,
            type=DepositOperation.TYPE_REFUND,
            amount=booking.deposit_amount,
            actor=actor,
            comment=comment or 'Сделка отменена',
        )
        booking.deposit_status = Booking.DEPOSIT_REFUNDED
        booking.save(update_fields=['deposit_status', 'updated_at'])
    elif booking.deposit_status == Booking.DEPOSIT_PENDING:
        booking.deposit_status = Booking.DEPOSIT_NONE
        booking.save(update_fields=['deposit_status', 'updated_at'])


def _settle_deposit(booking, withheld, actor, comment):
    from apps.payments.models import WalletTransaction
    from apps.payments.wallet import credit_wallet

    deposit = booking.deposit_amount
    if booking.deposit_status != Booking.DEPOSIT_HELD or deposit <= 0:
        return

    withheld = min(max(Decimal(withheld), Decimal('0')), deposit)
    refund = deposit - withheld

    if refund > 0:
        credit_wallet(
            booking.renter, refund, WalletTransaction.TYPE_DEPOSIT_REFUND, booking,
            comment=f'Возврат залога по сделке #{booking.pk}',
        )
        DepositOperation.objects.create(
            booking=booking, type=DepositOperation.TYPE_REFUND, amount=refund,
            actor=actor, comment=comment,
        )
    if withheld > 0:
        credit_wallet(
            booking.item.owner, withheld, WalletTransaction.TYPE_DEPOSIT_COMPENSATION, booking,
            comment=f'Удержанный залог по сделке #{booking.pk}',
        )
        DepositOperation.objects.create(
            booking=booking, type=DepositOperation.TYPE_WITHHOLD, amount=withheld,
            actor=actor, comment=comment,
        )

    if withheld == 0:
        booking.deposit_status = Booking.DEPOSIT_REFUNDED
    elif refund == 0:
        booking.deposit_status = Booking.DEPOSIT_WITHHELD
    else:
        booking.deposit_status = Booking.DEPOSIT_PARTIALLY_WITHHELD


def settle_completed_booking(booking_id, deposit_withheld=Decimal('0'), actor=None, comment=''):
    """
    Рассчитать завершённую сделку. Возвращает True, если расчёт сделан сейчас,
    False — если его не было нужно делать (уже рассчитана, нет оплаты).
    """
    from apps.bookings.serializers import booking_pays_in_cash
    from apps.payments.models import Payment, Transaction, WalletTransaction
    from apps.payments.wallet import credit_wallet, lock_profiles

    with transaction.atomic():
        booking = (
            # of=self: блокируем только сделку, а не присоединённые строки
            # пользователей — их профили блокирует lock_profiles в порядке id.
            Booking.objects.select_for_update(of=('self',))
            .select_related('item__owner', 'renter')
            .get(pk=booking_id)
        )
        if booking.escrow_status == Booking.ESCROW_RELEASED:
            logger.info('Booking #%s already settled, skipping', booking_id)
            return False

        if booking_pays_in_cash(booking):
            # Наличные (и залог) стороны передали из рук в руки: платформа их не
            # держала и не выплачивает. Комиссия автоматически не удерживается.
            booking.payments.filter(provider=Payment.PROVIDER_CASH).update(status=Payment.STATUS_COMPLETED)
            booking.status = Booking.STATUS_COMPLETED
            booking.escrow_status = Booking.ESCROW_NONE
            booking.deposit_status = Booking.DEPOSIT_NONE
            booking.save(update_fields=['status', 'escrow_status', 'deposit_status', 'updated_at'])
            logger.info('Booking #%s settled in cash, no payout from escrow', booking_id)
            return True

        payment = booking.payments.select_for_update().filter(status=Payment.STATUS_PAID).first()
        if not payment:
            logger.warning('No paid payment found for booking #%s during escrow release', booking_id)
            return False

        owner, renter = booking.item.owner, booking.renter
        lock_profiles(owner, renter)

        # Модель B: комиссия зафиксирована в сделке при создании и удерживается
        # из выплаты. Берём её из сделки, а не пересчитываем по текущей ставке —
        # иначе смена PLATFORM_COMMISSION_PERCENT задним числом меняла бы выплату.
        rental_income = booking.price_per_day * booking.days
        owner_payout = max(rental_income - booking.commission_amount, Decimal('0'))
        if owner_payout > 0:
            credit_wallet(
                owner, owner_payout, WalletTransaction.TYPE_RENT_PAYOUT, booking,
                comment=f'Аренда по сделке #{booking.pk}',
            )
            Transaction.objects.create(
                booking=booking,
                payment=payment,
                user=owner,
                type=Transaction.TYPE_PAYOUT,
                amount=owner_payout,
                currency='UZS',
                metadata={'source': 'release_escrow'},
            )

        _settle_deposit(booking, deposit_withheld, actor, comment)

        payment.status = Payment.STATUS_COMPLETED
        payment.save(update_fields=['status', 'updated_at'])

        booking.status = Booking.STATUS_COMPLETED
        booking.escrow_status = Booking.ESCROW_RELEASED
        booking.save(update_fields=['status', 'escrow_status', 'deposit_status', 'updated_at'])

    logger.info('Escrow released for booking #%s: owner payout=%s sums', booking_id, owner_payout)
    return True


def resolve_dispute(booking_id, deposit_withheld, actor, comment=''):
    """
    Сотрудник закрывает спор: сделка завершается, аренда уходит владельцу,
    deposit_withheld из залога — тоже владельцу, остальное — арендатору.
    """
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking_id)
        if booking.status != Booking.STATUS_DISPUTED:
            raise SettlementError('Спор можно закрыть только у сделки в статусе disputed.')
        if Decimal(deposit_withheld) > booking.deposit_amount:
            raise SettlementError(
                f'Удержать можно не больше залога ({booking.deposit_amount} сум).'
            )
        booking.transition_to(Booking.STATUS_COMPLETED)
        settle_completed_booking(booking.pk, deposit_withheld=deposit_withheld, actor=actor, comment=comment)
    booking.refresh_from_db()
    return booking

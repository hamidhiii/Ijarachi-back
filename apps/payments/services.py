import logging
from decimal import Decimal

from django.utils import timezone

from apps.bookings.models import Booking, DepositOperation

from .models import Payment, Transaction

logger = logging.getLogger('apps.payments')

# Из каких статусов сделку переводит в paid поступившая оплата.
AWAITING_PAYMENT_STATUSES = (Booking.STATUS_DRAFT, Booking.STATUS_PENDING_PAYMENT)


def finalize_paid_payment(payment: Payment):
    """
    Платёж прошёл (вебхук провайдера или заглушка): сделка — paid, деньги в
    эскроу, залог удержан, контакты раскрыты, открыт чат сделки. Вызывать
    внутри transaction.atomic.
    """
    booking = payment.booking
    if payment.status in [Payment.STATUS_PAID, Payment.STATUS_COMPLETED]:
        return booking
    payment.status = Payment.STATUS_PAID
    payment.save(update_fields=['status', 'updated_at'])

    amount_uzs = (Decimal(str(payment.amount)) / Decimal('100')).quantize(Decimal('1'))
    Transaction.objects.create(
        booking=booking,
        payment=payment,
        user=booking.renter,
        type=Transaction.TYPE_ESCROW_HOLD,
        amount=amount_uzs,
        currency='UZS',
        metadata={'provider': payment.provider},
    )

    if booking.status not in AWAITING_PAYMENT_STATUSES:
        # Деньги пришли за сделку, которая уже отменена (истекла, отказ владельца).
        # Воскрешать её нельзя: её даты могли уже занять — платёж уходит на
        # ручной возврат, сделка остаётся как есть.
        logger.error(
            'Payment #%s arrived for booking #%s in status %s — booking left untouched, refund manually',
            payment.pk, booking.pk, booking.status,
        )
        return booking

    booking.status = Booking.STATUS_PAID
    booking.escrow_status = Booking.ESCROW_HELD
    booking.contact_revealed_at = timezone.now()
    update_fields = ['status', 'escrow_status', 'contact_revealed_at', 'updated_at']
    if booking.deposit_amount > 0:
        booking.deposit_status = Booking.DEPOSIT_HELD
        update_fields.append('deposit_status')
    booking.save(update_fields=update_fields)
    if booking.deposit_amount > 0:
        DepositOperation.objects.create(
            booking=booking,
            type=DepositOperation.TYPE_HOLD,
            amount=booking.deposit_amount,
            comment=f'Оплата через {payment.get_provider_display()}',
        )

    try:
        from apps.chat.models import Conversation
        from apps.notifications.models import Notification
        from apps.notifications.tasks import create_notification

        conversation = Conversation.objects.filter(deal=booking).first()
        if not conversation:
            # Тот же арендатор мог уже написать владельцу по этому объявлению до
            # брони — переиспользуем этот диалог вместо создания второго рядом,
            # просто проставляя ему deal_id задним числом.
            conversation = Conversation.objects.filter(
                listing=booking.item, participants=booking.renter, deal__isnull=True,
            ).first()
        if not conversation:
            conversation = Conversation.objects.create(deal=booking, listing=booking.item)
        elif not conversation.deal_id:
            conversation.deal = booking
            conversation.save(update_fields=['deal', 'updated_at'])
        conversation.participants.add(booking.renter, booking.item.owner)
        payload = {
            'booking_id': booking.pk,
            'message': 'Чат по сделке открыт',
            'link': f'/messages?deal={booking.pk}',
        }
        create_notification(booking.renter, Notification.TYPE_CHAT, payload)
        create_notification(booking.item.owner, Notification.TYPE_CHAT, payload)

        create_notification(booking.renter, Notification.TYPE_PAYMENT, {
            'title': 'Оплата прошла',
            'message': f'Оплата сделки «{booking.item.title}» прошла успешно.',
            'booking_id': booking.pk,
        })
        create_notification(booking.item.owner, Notification.TYPE_PAYMENT, {
            'title': 'Оплата прошла',
            'message': f'Арендатор оплатил «{booking.item.title}».',
            'booking_id': booking.pk,
        })
    except Exception as exc:
        logger.exception('Failed to open paid booking chat for booking #%s: %s', booking.pk, exc)

    return booking

import hashlib
import base64
import logging
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Payment
from apps.bookings.models import Booking

logger = logging.getLogger('apps.payments')


def finalize_paid_payment(payment: Payment):
    booking = payment.booking
    if payment.status in [Payment.STATUS_PAID, Payment.STATUS_COMPLETED]:
        return booking
    payment.status = Payment.STATUS_PAID
    payment.save(update_fields=['status', 'updated_at'])

    booking.status = Booking.STATUS_PAID
    booking.escrow_status = Booking.ESCROW_HELD
    booking.contact_revealed_at = timezone.now()
    update_fields = ['status', 'escrow_status', 'contact_revealed_at', 'updated_at']
    booking.save(update_fields=update_fields)

    from apps.payments.models import Transaction

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

    try:
        from apps.chat.models import Conversation
        from apps.notifications.models import Notification
        from apps.notifications.tasks import create_notification

        conversation = Conversation.objects.filter(deal=booking).first()
        if not conversation:
            conversation = Conversation.objects.create(deal=booking)
        conversation.participants.add(booking.renter, booking.item.owner)
        payload = {'booking_id': booking.pk, 'message': 'Чат по сделке открыт'}
        create_notification(booking.renter, Notification.TYPE_CHAT, payload)
        create_notification(booking.item.owner, Notification.TYPE_CHAT, payload)
    except Exception as exc:
        logger.exception('Failed to open paid booking chat for booking #%s: %s', booking.pk, exc)

    return booking


# ─── Payme ────────────────────────────────────────────────────────────────────

class PaymeWebhookView(APIView):
    """
    POST /api/v1/payments/payme/webhook/
    Handles Payme merchant API (JSON-RPC 2.0).
    """
    permission_classes = []

    def _verify_auth(self, request) -> bool:
        auth = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth.startswith('Basic '):
            return False
        try:
            decoded = base64.b64decode(auth[6:]).decode('utf-8')
            _, password = decoded.split(':', 1)
            return password == settings.PAYME_SECRET_KEY
        except Exception:
            return False

    def post(self, request):
        if not self._verify_auth(request):
            return Response(
                {'error': {'code': -32504, 'message': 'Insufficient privilege'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        body = request.data
        method = body.get('method', '')
        params = body.get('params', {})
        rpc_id = body.get('id')

        logger.info('Payme webhook: method=%s id=%s', method, rpc_id)

        handler = {
            'CheckPerformTransaction': self._check_perform,
            'CreateTransaction': self._create_transaction,
            'PerformTransaction': self._perform_transaction,
            'CancelTransaction': self._cancel_transaction,
            'CheckTransaction': self._check_transaction,
        }.get(method)

        if not handler:
            return Response({'id': rpc_id, 'error': {'code': -32601, 'message': 'Method not found'}})

        return handler(params, rpc_id)

    def _check_perform(self, params, rpc_id):
        booking_id = params.get('account', {}).get('booking_id')
        try:
            booking = Booking.objects.get(pk=booking_id, status=Booking.STATUS_PAYMENT_PENDING)
            amount = int(params.get('amount', 0))
            expected = int(booking.total_price * 100)  # convert to tiyin
            if amount != expected:
                return Response({'id': rpc_id, 'error': {'code': -31001, 'message': 'Wrong amount'}})
            return Response({'id': rpc_id, 'result': {'allow': True}})
        except Booking.DoesNotExist:
            return Response({'id': rpc_id, 'error': {'code': -31050, 'message': 'Booking not found'}})

    def _create_transaction(self, params, rpc_id):
        booking_id = params.get('account', {}).get('booking_id')
        transaction_id = params.get('id')
        amount = params.get('amount', 0)

        try:
            booking = Booking.objects.get(pk=booking_id)
        except Booking.DoesNotExist:
            return Response({'id': rpc_id, 'error': {'code': -31050, 'message': 'Booking not found'}})

        payment, created = Payment.objects.get_or_create(
            provider_transaction_id=transaction_id,
            defaults={
                'booking': booking,
                'provider': Payment.PROVIDER_PAYME,
                'amount': amount,
                'status': Payment.STATUS_PENDING,
                'raw_request': params,
            }
        )

        return Response({'id': rpc_id, 'result': {
            'create_time': int(payment.created_at.timestamp() * 1000),
            'transaction': str(payment.pk),
            'state': 1,
        }})

    def _perform_transaction(self, params, rpc_id):
        transaction_id = params.get('id')
        try:
            payment = Payment.objects.select_related('booking').get(
                provider_transaction_id=transaction_id,
                provider=Payment.PROVIDER_PAYME,
            )
        except Payment.DoesNotExist:
            return Response({'id': rpc_id, 'error': {'code': -31003, 'message': 'Transaction not found'}})

        with transaction.atomic():
            booking = finalize_paid_payment(payment)

            logger.info(
                'Payment confirmed (Payme): booking #%s, amount=%s tiyin',
                booking.pk, payment.amount
            )

        return Response({'id': rpc_id, 'result': {
            'transaction': str(payment.pk),
            'perform_time': int(payment.updated_at.timestamp() * 1000),
            'state': 2,
        }})

    def _cancel_transaction(self, params, rpc_id):
        transaction_id = params.get('id')
        reason = params.get('reason', 0)
        try:
            payment = Payment.objects.select_related('booking').get(
                provider_transaction_id=transaction_id,
            )
        except Payment.DoesNotExist:
            return Response({'id': rpc_id, 'error': {'code': -31003, 'message': 'Transaction not found'}})

        with transaction.atomic():
            payment.status = Payment.STATUS_FAILED
            payment.save(update_fields=['status', 'updated_at'])

            booking = payment.booking
            if booking.status in (Booking.STATUS_PENDING_PAYMENT, Booking.STATUS_PAID):
                booking.transition_to(Booking.STATUS_CANCELLED)
                booking.escrow_status = Booking.ESCROW_REFUNDED
                booking.save(update_fields=['escrow_status', 'updated_at'])
                # Unblock dates
                try:
                    from apps.catalog.models import ItemAvailability
                    avail = ItemAvailability.objects.get(item=booking.item)
                    avail.unblock_range(booking.start_date, booking.end_date)
                except Exception:
                    pass

            logger.warning('Payment cancelled (Payme): booking #%s, reason=%s', booking.pk, reason)

        return Response({'id': rpc_id, 'result': {
            'transaction': str(payment.pk),
            'cancel_time': int(payment.updated_at.timestamp() * 1000),
            'state': -1,
        }})

    def _check_transaction(self, params, rpc_id):
        transaction_id = params.get('id')
        try:
            payment = Payment.objects.get(provider_transaction_id=transaction_id)
            state = 2 if payment.status in [Payment.STATUS_PAID, Payment.STATUS_COMPLETED] else 1
            return Response({'id': rpc_id, 'result': {
                'create_time': int(payment.created_at.timestamp() * 1000),
                'perform_time': int(payment.updated_at.timestamp() * 1000),
                'cancel_time': 0,
                'transaction': str(payment.pk),
                'state': state,
                'reason': None,
            }})
        except Payment.DoesNotExist:
            return Response({'id': rpc_id, 'error': {'code': -31003, 'message': 'Transaction not found'}})


# ─── Click ────────────────────────────────────────────────────────────────────

class ClickWebhookView(APIView):
    """
    POST /api/v1/payments/click/webhook/
    Handles Click SHOP API (Prepare + Complete steps).
    """
    permission_classes = []

    def _verify_sign(self, data) -> bool:
        sign_string = (
            f"{data.get('click_trans_id')}"
            f"{data.get('service_id')}"
            f"{settings.CLICK_SECRET_KEY}"
            f"{data.get('merchant_trans_id')}"
            f"{data.get('amount')}"
            f"{data.get('action')}"
            f"{data.get('sign_time')}"
        )
        expected = hashlib.md5(sign_string.encode()).hexdigest()
        return expected == data.get('sign_string', '')

    def post(self, request):
        data = request.data
        action = int(data.get('action', -1))

        if not self._verify_sign(data):
            return Response({'error': -1, 'error_note': 'Invalid sign'})

        booking_id = data.get('merchant_trans_id')
        click_trans_id = data.get('click_trans_id')
        amount = data.get('amount', 0)

        try:
            booking = Booking.objects.get(pk=booking_id)
        except Booking.DoesNotExist:
            return Response({'error': -5, 'error_note': 'User does not exist'})

        if action == 0:
            # Prepare
            logger.info('Click Prepare: booking #%s, amount=%s', booking_id, amount)
            Payment.objects.get_or_create(
                provider_transaction_id=str(click_trans_id),
                defaults={
                    'booking': booking,
                    'provider': Payment.PROVIDER_CLICK,
                    'amount': int(float(amount) * 100),
                    'status': Payment.STATUS_PENDING,
                    'raw_request': data,
                }
            )
            return Response({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': booking_id,
                'merchant_prepare_id': booking_id,
                'error': 0,
                'error_note': 'Success',
            })

        elif action == 1:
            # Complete
            try:
                payment = Payment.objects.select_related('booking').get(
                    provider_transaction_id=str(click_trans_id),
                )
            except Payment.DoesNotExist:
                return Response({'error': -6, 'error_note': 'Transaction not found'})

            with transaction.atomic():
                booking = finalize_paid_payment(payment)
                logger.info('Payment confirmed (Click): booking #%s', booking.pk)

            return Response({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': booking_id,
                'merchant_confirm_id': payment.pk,
                'error': 0,
                'error_note': 'Success',
            })

        return Response({'error': -3, 'error_note': 'Action not found'})

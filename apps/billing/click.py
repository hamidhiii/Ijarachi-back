"""
Click SHOP API для заказов: Prepare (action=0) и Complete (action=1).

merchant_trans_id — id заказа, сумма — в сумах. Подпись — md5 полей запроса и
секретного ключа; у Complete в неё входит merchant_prepare_id (его мы отдали в
Prepare, это тот же id заказа). Click повторяет запросы, поэтому оба шага
идемпотентны: повторный Complete оплаченного заказа отвечает «уже оплачен».
"""
import hashlib
import hmac
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction

from .models import BillingOrder
from .services import OrderNotPayable, cancel_order, check_order_payable, mark_order_paid

logger = logging.getLogger('apps.billing')

ACTION_PREPARE = 0
ACTION_COMPLETE = 1

OK = 0
ERR_SIGN = -1
ERR_AMOUNT = -2
ERR_ACTION = -3
ERR_ALREADY_PAID = -4
ERR_ORDER_NOT_FOUND = -5
ERR_TX_NOT_FOUND = -6
ERR_REQUEST = -8
ERR_CANCELLED = -9

NOTES = {
    OK: 'Success',
    ERR_SIGN: 'SIGN CHECK FAILED!',
    ERR_AMOUNT: 'Incorrect parameter amount',
    ERR_ACTION: 'Action not found',
    ERR_ALREADY_PAID: 'Already paid',
    ERR_ORDER_NOT_FOUND: 'Order does not exist',
    ERR_TX_NOT_FOUND: 'Transaction does not exist',
    ERR_REQUEST: 'Error in request from click',
    ERR_CANCELLED: 'Transaction cancelled',
}


def expected_sign(data, action):
    prepare_id = data.get('merchant_prepare_id', '') if action == ACTION_COMPLETE else ''
    raw = (
        f"{data.get('click_trans_id', '')}{data.get('service_id', '')}{settings.CLICK_SECRET_KEY}"
        f"{data.get('merchant_trans_id', '')}{prepare_id}{data.get('amount', '')}"
        f"{data.get('action', '')}{data.get('sign_time', '')}"
    )
    return hashlib.md5(raw.encode()).hexdigest()


def handle(data) -> dict:
    data = {key: (value[0] if isinstance(value, list) else value) for key, value in dict(data).items()}
    response = {
        'click_trans_id': data.get('click_trans_id'),
        'merchant_trans_id': data.get('merchant_trans_id'),
    }

    def reply(code, **extra):
        return {**response, **extra, 'error': code, 'error_note': NOTES[code]}

    try:
        action = int(data.get('action'))
    except (TypeError, ValueError):
        return reply(ERR_REQUEST)
    if action not in (ACTION_PREPARE, ACTION_COMPLETE):
        return reply(ERR_ACTION)
    if not settings.CLICK_SECRET_KEY or not hmac.compare_digest(
        expected_sign(data, action), str(data.get('sign_string', '')),
    ):
        return reply(ERR_SIGN)

    try:
        order_id = int(data.get('merchant_trans_id'))
        amount = Decimal(str(data.get('amount')))
    except (TypeError, ValueError, InvalidOperation):
        return reply(ERR_REQUEST)

    with transaction.atomic():
        order = (
            BillingOrder.objects.select_for_update(of=('self',))
            .select_related('plan', 'item', 'user').filter(pk=order_id).first()
        )
        if order is None:
            return reply(ERR_ORDER_NOT_FOUND)
        if amount != order.amount:
            return reply(ERR_AMOUNT)
        click_trans_id = str(data.get('click_trans_id') or '')
        if action == ACTION_PREPARE:
            return _prepare(order, click_trans_id, data, reply)
        return _complete(order, click_trans_id, data, reply)


def _prepare(order, click_trans_id, data, reply):
    if order.status == BillingOrder.STATUS_PAID:
        return reply(ERR_ALREADY_PAID)
    if order.status == BillingOrder.STATUS_CANCELLED:
        return reply(ERR_CANCELLED)
    if order.provider_transaction_id and not (
        order.provider == BillingOrder.PROVIDER_CLICK and order.provider_transaction_id == click_trans_id
    ):
        # Заказ уже начат другой транзакцией (Payme или другой платёж Click).
        return reply(ERR_CANCELLED)
    try:
        check_order_payable(order)
    except OrderNotPayable:
        return reply(ERR_CANCELLED)
    order.provider = BillingOrder.PROVIDER_CLICK
    order.provider_transaction_id = click_trans_id
    order.raw = {'click_paydoc_id': data.get('click_paydoc_id'), 'prepare_sign_time': data.get('sign_time')}
    order.save(update_fields=['provider', 'provider_transaction_id', 'raw'])
    return reply(OK, merchant_prepare_id=order.pk)


def _complete(order, click_trans_id, data, reply):
    if str(data.get('merchant_prepare_id')) != str(order.pk) or order.provider_transaction_id != click_trans_id:
        return reply(ERR_TX_NOT_FOUND)
    if order.status == BillingOrder.STATUS_PAID:
        return reply(ERR_ALREADY_PAID, merchant_confirm_id=order.pk)
    if order.status == BillingOrder.STATUS_CANCELLED:
        return reply(ERR_CANCELLED)
    try:
        click_error = int(data.get('error') or 0)
    except (TypeError, ValueError):
        click_error = 0
    if click_error < 0:
        # Платёж не прошёл на стороне Click — заказ закрываем.
        cancel_order(order.pk)
        logger.warning('Click: order #%s cancelled by Click, error %s', order.pk, click_error)
        return reply(ERR_CANCELLED)
    mark_order_paid(order.pk)
    logger.info('Click: order #%s paid, click_trans_id %s', order.pk, click_trans_id)
    return reply(OK, merchant_confirm_id=order.pk)

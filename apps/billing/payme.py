"""
Payme Merchant API (JSON-RPC 2.0) для заказов: тарифы и продвижение.

Счёт — `account.order_id`, сумма — в тийинах. CheckPerformTransaction
отдаёт фискальные данные чека (detail) — см. receipt_detail. Протокол:
CheckPerformTransaction → CreateTransaction → PerformTransaction, отмена —
CancelTransaction; CheckTransaction и GetStatement — сверка. Ответ всегда
HTTP 200, ошибка — в поле error. Транзакция, не проведённая за 12 часов,
отменяется (reason 4). Проведённую не отменяем: услуга уже выдана (-31007).
"""
import base64
import binascii
import hmac
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import BillingOrder
from .services import OrderNotPayable, check_order_payable, mark_order_paid

logger = logging.getLogger('apps.billing')

TIMEOUT_MS = 12 * 60 * 60 * 1000
REASON_TIMEOUT = 4

ERR_AUTH = -32504
ERR_METHOD = -32601
ERR_PARAMS = -32600
ERR_AMOUNT = -31001
ERR_TX_NOT_FOUND = -31003
ERR_CANNOT_CANCEL = -31007
ERR_CANNOT_PERFORM = -31008
ERR_ORDER_NOT_FOUND = -31050
ERR_ORDER_UNAVAILABLE = -31051
ERR_ORDER_BUSY = -31052

MESSAGES = {
    ERR_AUTH: ('Недостаточно привилегий', 'Ruxsat yetarli emas', 'Insufficient privilege'),
    ERR_METHOD: ('Метод не найден', 'Metod topilmadi', 'Method not found'),
    ERR_PARAMS: ('Неверный запрос', 'Noto‘g‘ri so‘rov', 'Invalid request'),
    ERR_AMOUNT: ('Неверная сумма', 'Noto‘g‘ri summa', 'Wrong amount'),
    ERR_TX_NOT_FOUND: ('Транзакция не найдена', 'Tranzaksiya topilmadi', 'Transaction not found'),
    ERR_CANNOT_CANCEL: ('Услуга оказана, отмена невозможна', 'Xizmat ko‘rsatilgan, bekor qilib bo‘lmaydi', 'Cannot cancel'),
    ERR_CANNOT_PERFORM: ('Невозможно выполнить операцию', 'Amalni bajarib bo‘lmaydi', 'Cannot perform'),
    ERR_ORDER_NOT_FOUND: ('Заказ не найден', 'Buyurtma topilmadi', 'Order not found'),
    ERR_ORDER_UNAVAILABLE: ('Заказ нельзя оплатить', 'Buyurtmani to‘lab bo‘lmaydi', 'Order is not payable'),
    ERR_ORDER_BUSY: ('Заказ уже оплачивается', 'Buyurtma to‘lanmoqda', 'Order has another transaction'),
}


class PaymeError(Exception):
    def __init__(self, code, data=None):
        super().__init__(code)
        self.code = code
        self.data = data

    def as_dict(self):
        ru, uz, en = MESSAGES[self.code]
        error = {'code': self.code, 'message': {'ru': ru, 'uz': uz, 'en': en}}
        if self.data is not None:
            error['data'] = self.data
        return error


def now_ms():
    return int(timezone.now().timestamp() * 1000)


def authorized(header: str) -> bool:
    """Basic-авторизация Payme: логин Paycom, пароль — ключ кассы."""
    if not settings.PAYME_SECRET_KEY or not header.startswith('Basic '):
        return False
    try:
        login, _, password = base64.b64decode(header[6:]).decode('utf-8').partition(':')
    except (binascii.Error, UnicodeDecodeError):
        return False
    return login == 'Paycom' and hmac.compare_digest(password, settings.PAYME_SECRET_KEY)


def handle(body: dict) -> dict:
    """Один JSON-RPC запрос → ответ ({result} или {error}), id подставляется."""
    rpc_id = body.get('id') if isinstance(body, dict) else None
    try:
        if not isinstance(body, dict) or not isinstance(body.get('params'), dict):
            raise PaymeError(ERR_PARAMS)
        method = METHODS.get(body.get('method'))
        if method is None:
            raise PaymeError(ERR_METHOD)
        return {'jsonrpc': '2.0', 'id': rpc_id, 'result': method(body['params'])}
    except PaymeError as exc:
        return {'jsonrpc': '2.0', 'id': rpc_id, 'error': exc.as_dict()}


# ─── Методы ──────────────────────────────────────────────────────────────────

def _order_for(params, lock=False):
    order_id = (params.get('account') or {}).get('order_id')
    qs = BillingOrder.objects.select_related('plan', 'item', 'user')
    if lock:
        qs = qs.select_for_update(of=('self',))
    try:
        return qs.get(pk=int(order_id))
    except (BillingOrder.DoesNotExist, TypeError, ValueError):
        raise PaymeError(ERR_ORDER_NOT_FOUND, 'order_id')


def _check_payable(order, params):
    try:
        amount = int(params.get('amount'))
    except (TypeError, ValueError):
        raise PaymeError(ERR_AMOUNT)
    if amount != order.amount_tiyin:
        raise PaymeError(ERR_AMOUNT)
    try:
        check_order_payable(order)
    except OrderNotPayable:
        raise PaymeError(ERR_ORDER_UNAVAILABLE, 'order_id')


def receipt_title(order):
    """Название позиции в чеке — узбекский, латиница: что куплено и на какой срок."""
    from .promotions import promotion_days

    if order.kind == BillingOrder.KIND_PLAN:
        days = settings.BILLING_PERIOD_DAYS
        term = '1 oy' if days == 30 else f'{days} kun'
        return f'Rentoo {order.plan.get_code_display()} tarifi — {term}'
    days = promotion_days(order.promotion)
    if order.promotion == BillingOrder.PROMO_VIP:
        return f"Rentoo VIP e'lon — {days} kun"
    return f"Rentoo e'lonni TOPga ko'tarish — {days} kun"


def receipt_detail(order):
    """
    Фискальный чек для CheckPerformTransaction: одна позиция на заказ.
    price × count обязаны точно совпасть с amount транзакции, иначе Payme
    отклонит платёж, — поэтому цена берётся из той же суммы заказа, что и
    проверка amount, а несовпадение — ошибка у нас, а не у покупателя.
    """
    code, package_code = settings.PAYME_FISCAL_MXIK, settings.PAYME_FISCAL_PACKAGE_CODE
    if order.kind == BillingOrder.KIND_PROMOTION:
        # Свой MXIK/единица у продвижения, если заданы; иначе — как у тарифа.
        code = settings.PAYME_FISCAL_MXIK_PROMO or code
        package_code = settings.PAYME_FISCAL_PACKAGE_CODE_PROMO or package_code
    items = [{
        'title': receipt_title(order),
        'price': order.amount_tiyin,
        'count': 1,
        'code': code,
        'package_code': package_code,
        'vat_percent': settings.PAYME_FISCAL_VAT_PERCENT,
    }]
    total = sum(item['price'] * item['count'] for item in items)
    if total != order.amount_tiyin:
        raise PaymeError(ERR_AMOUNT)
    if not items[0]['code'] or not items[0]['package_code']:
        # Платёж пройдёт, но чек не попадёт в налоговую — заметно в логах.
        logger.warning('Payme: не задан MXIK или код единицы (PAYME_FISCAL_*) — заказ #%s', order.pk)
    return {'receipt_type': 0, 'items': items}


def check_perform_transaction(params):
    order = _order_for(params)
    _check_payable(order, params)
    if order.provider_state == BillingOrder.PAYME_CREATED:
        raise PaymeError(ERR_ORDER_BUSY, 'order_id')
    return {'allow': True, 'detail': receipt_detail(order)}


def _tx(params, lock=True):
    qs = BillingOrder.objects.filter(provider=BillingOrder.PROVIDER_PAYME, provider_transaction_id=str(params.get('id') or ''))
    if lock:
        qs = qs.select_for_update()
    order = qs.first()
    if order is None or not params.get('id'):
        raise PaymeError(ERR_TX_NOT_FOUND)
    return order


def _timed_out(order):
    return order.provider_state == BillingOrder.PAYME_CREATED and now_ms() - order.provider_create_time > TIMEOUT_MS


def _cancel(order, state, reason):
    order.provider_state = state
    order.provider_cancel_time = now_ms()
    order.cancel_reason = reason
    if order.status == BillingOrder.STATUS_PENDING:
        order.status = BillingOrder.STATUS_CANCELLED
    order.save(update_fields=['provider_state', 'provider_cancel_time', 'cancel_reason', 'status'])


def create_transaction(params):
    tx_id = str(params.get('id') or '')
    if not tx_id:
        raise PaymeError(ERR_PARAMS)
    with transaction.atomic():
        existing = BillingOrder.objects.select_for_update().filter(
            provider=BillingOrder.PROVIDER_PAYME, provider_transaction_id=tx_id,
        ).first()
        if existing is not None:
            if existing.provider_state != BillingOrder.PAYME_CREATED:
                raise PaymeError(ERR_CANNOT_PERFORM)
            if not _timed_out(existing):
                return _tx_state(existing)
            # Отмена по таймауту должна сохраниться — ошибку бросаем после коммита.
            _cancel(existing, BillingOrder.PAYME_CANCELLED, REASON_TIMEOUT)
        else:
            order = _order_for(params, lock=True)
            _check_payable(order, params)
            if order.provider_transaction_id:
                # У заказа уже есть другая транзакция Payme (или он начат в Click).
                raise PaymeError(ERR_ORDER_BUSY, 'order_id')
            order.provider = BillingOrder.PROVIDER_PAYME
            order.provider_transaction_id = tx_id
            order.provider_state = BillingOrder.PAYME_CREATED
            order.provider_create_time = now_ms()
            order.raw = {'payme_time': params.get('time'), 'payme_account': params.get('account')}
            order.save(update_fields=[
                'provider', 'provider_transaction_id', 'provider_state', 'provider_create_time', 'raw',
            ])
            return _tx_state(order)
    raise PaymeError(ERR_CANNOT_PERFORM)


def perform_transaction(params):
    with transaction.atomic():
        order = _tx(params)
        if order.provider_state == BillingOrder.PAYME_PERFORMED:
            return _performed(order)
        if order.provider_state != BillingOrder.PAYME_CREATED:
            raise PaymeError(ERR_CANNOT_PERFORM)
        if not _timed_out(order):
            order.provider_state = BillingOrder.PAYME_PERFORMED
            order.provider_perform_time = now_ms()
            order.save(update_fields=['provider_state', 'provider_perform_time'])
            mark_order_paid(order.pk)
            logger.info('Payme: order #%s paid, tx %s', order.pk, order.provider_transaction_id)
            return _performed(order)
        # Отмена по таймауту должна сохраниться — ошибку бросаем после коммита.
        _cancel(order, BillingOrder.PAYME_CANCELLED, REASON_TIMEOUT)
    raise PaymeError(ERR_CANNOT_PERFORM)


def _performed(order):
    return {'transaction': str(order.pk), 'perform_time': order.provider_perform_time, 'state': order.provider_state}


@transaction.atomic
def cancel_transaction(params):
    order = _tx(params)
    if order.provider_state == BillingOrder.PAYME_CREATED:
        _cancel(order, BillingOrder.PAYME_CANCELLED, params.get('reason'))
        logger.warning('Payme: order #%s cancelled before payment, reason %s', order.pk, params.get('reason'))
    elif order.provider_state == BillingOrder.PAYME_PERFORMED:
        # Тариф или продвижение уже действуют — возврат только через поддержку.
        raise PaymeError(ERR_CANNOT_CANCEL)
    return {'transaction': str(order.pk), 'cancel_time': order.provider_cancel_time, 'state': order.provider_state}


def check_transaction(params):
    order = _tx(params, lock=False)
    return {
        'create_time': order.provider_create_time or 0,
        'perform_time': order.provider_perform_time or 0,
        'cancel_time': order.provider_cancel_time or 0,
        'transaction': str(order.pk),
        'state': order.provider_state,
        'reason': order.cancel_reason,
    }


def get_statement(params):
    try:
        start, end = int(params['from']), int(params['to'])
    except (KeyError, TypeError, ValueError):
        raise PaymeError(ERR_PARAMS)
    orders = BillingOrder.objects.filter(
        provider=BillingOrder.PROVIDER_PAYME,
        provider_create_time__gte=start, provider_create_time__lte=end,
    ).order_by('provider_create_time')
    return {'transactions': [
        {
            'id': order.provider_transaction_id,
            'time': order.raw.get('payme_time'),
            'amount': order.amount_tiyin,
            'account': {'order_id': order.pk},
            'create_time': order.provider_create_time,
            'perform_time': order.provider_perform_time or 0,
            'cancel_time': order.provider_cancel_time or 0,
            'transaction': str(order.pk),
            'state': order.provider_state,
            'reason': order.cancel_reason,
        }
        for order in orders
    ]}


def _tx_state(order):
    return {
        'create_time': order.provider_create_time,
        'transaction': str(order.pk),
        'state': order.provider_state,
    }


METHODS = {
    'CheckPerformTransaction': check_perform_transaction,
    'CreateTransaction': create_transaction,
    'PerformTransaction': perform_transaction,
    'CancelTransaction': cancel_transaction,
    'CheckTransaction': check_transaction,
    'GetStatement': get_statement,
}

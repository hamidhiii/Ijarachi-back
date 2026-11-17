"""Ссылки на страницы оплаты Click и Payme для заказа (тариф или продвижение)."""
import base64
from urllib.parse import urlencode

from django.conf import settings


def return_url(order) -> str:
    return settings.BILLING_RETURN_URL_TEMPLATE.format(id=order.pk)


def click_url(order) -> str:
    """my.click.uz: сумма в сумах, transaction_param = merchant_trans_id = id заказа."""
    query = urlencode({
        'service_id': settings.CLICK_SERVICE_ID,
        'merchant_id': settings.CLICK_MERCHANT_ID,
        'amount': int(order.amount),
        'transaction_param': order.pk,
        'return_url': return_url(order),
    })
    return f'https://my.click.uz/services/pay?{query}'


def payme_url(order) -> str:
    """checkout.paycom.uz: параметры в base64, сумма в тийинах, счёт — order_id."""
    raw = (
        f'm={settings.PAYME_MERCHANT_ID};'
        f'ac.order_id={order.pk};'
        f'a={order.amount_tiyin};'
        f'c={return_url(order)}'
    )
    return 'https://checkout.paycom.uz/' + base64.b64encode(raw.encode()).decode('ascii')

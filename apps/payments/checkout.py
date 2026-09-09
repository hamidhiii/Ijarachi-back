"""
Строит реальные ссылки на страницу оплаты провайдера для POST /deals/{id}/pay/.
Раньше сюда подставлялся deep-link-заглушка (rentoo://pay/...) — теперь настоящие
чекаут-URL Click/Payme, на которые can открыть браузер/webview.
"""
import base64

from django.conf import settings

from .models import Payment


def return_url_for(booking_id: int) -> str:
    return settings.PAYMENT_RETURN_URL_TEMPLATE.format(id=booking_id)


def build_click_url(payment: Payment) -> str:
    """
    my.click.uz Checkout: amount — целые сумы (не тийины), transaction_param —
    то же значение, что ClickWebhookView ждёт в merchant_trans_id (id сделки).
    """
    amount_sum = int(payment.amount) // 100
    params = {
        'service_id': settings.CLICK_SERVICE_ID,
        'merchant_id': settings.CLICK_MERCHANT_ID,
        'amount': amount_sum,
        'transaction_param': payment.booking_id,
        'return_url': return_url_for(payment.booking_id),
    }
    query = '&'.join(f'{k}={v}' for k, v in params.items())
    return f'https://my.click.uz/services/pay?{query}'


def build_payme_url(payment: Payment) -> str:
    """
    Payme Checkout: параметры кодируются в base64 и идут частью пути.
    Сумма — в тийинах (как и хранится в Payment.amount).
    """
    raw = (
        f'm={settings.PAYME_MERCHANT_ID};'
        f'ac.booking_id={payment.booking_id};'
        f'a={int(payment.amount)};'
        f'c={return_url_for(payment.booking_id)}'
    )
    encoded = base64.b64encode(raw.encode('utf-8')).decode('ascii')
    return f'https://checkout.paycom.uz/{encoded}'


def build_redirect_url(payment: Payment) -> str:
    if payment.provider == Payment.PROVIDER_CLICK:
        return build_click_url(payment)
    if payment.provider == Payment.PROVIDER_PAYME:
        return build_payme_url(payment)
    raise ValueError(f'No checkout URL builder for provider={payment.provider!r}')

"""
Способы оплаты сделки за единым интерфейсом.

POST /deals/{id}/pay/ создаёт Payment и вызывает provider.start(payment), не
зная, кто стоит за провайдером:

- CashProvider — наличные при получении, работают в любом режиме;
- ClickProvider / PaymeProvider — настоящий чекаут, только PAYMENTS_MODE=live;
- StubProvider — заглушка вместо Click/Payme при PAYMENTS_MODE=stub: оплата
  подтверждается сразу, без денег. Разрешена только в dev/staging
  (core.runtime_modes): в prod сервер с ней не стартует, а сама заглушка ещё
  раз проверяет режим перед подтверждением.

При PAYMENTS_MODE=off онлайн-оплата недоступна — get_provider бросает
PaymentsUnavailable, остаются наличные.
"""
from core.runtime_modes import payments_live, payments_stub_active

from .checkout import build_click_url, build_payme_url, return_url_for
from .models import Payment

ONLINE_PROVIDERS = (Payment.PROVIDER_CLICK, Payment.PROVIDER_PAYME)


class PaymentsUnavailable(Exception):
    """Запрошенный способ оплаты сейчас выключен настройками."""


class PaymentProvider:
    code: str = ''
    online: bool = True

    def start(self, payment: Payment) -> str | None:
        """Начать оплату. Возвращает ссылку, куда отправить пользователя, или None."""
        raise NotImplementedError


class CashProvider(PaymentProvider):
    code = Payment.PROVIDER_CASH
    online = False

    def start(self, payment):
        return None


class ClickProvider(PaymentProvider):
    code = Payment.PROVIDER_CLICK

    def start(self, payment):
        return build_click_url(payment)


class PaymeProvider(PaymentProvider):
    code = Payment.PROVIDER_PAYME

    def start(self, payment):
        return build_payme_url(payment)


class StubProvider(PaymentProvider):
    """
    Подтверждает оплату сразу же, без денег. Ссылка ведёт обратно на страницу
    сделки — фронт проходит тот же путь, что и после настоящего чекаута.
    """
    code = Payment.PROVIDER_STUB

    def start(self, payment):
        if not payments_stub_active():
            raise PaymentsUnavailable('Заглушка оплаты запрещена в этом окружении.')
        from .services import finalize_paid_payment

        payment.raw_request = {'stub': True}
        payment.save(update_fields=['raw_request', 'updated_at'])
        finalize_paid_payment(payment)
        return return_url_for(payment.booking_id)


def get_provider(requested: str) -> PaymentProvider:
    """Провайдер для способа оплаты, который выбрал пользователь."""
    if requested == Payment.PROVIDER_CASH:
        return CashProvider()
    if requested not in ONLINE_PROVIDERS:
        raise PaymentsUnavailable(f'Неизвестный способ оплаты: {requested}.')
    if payments_live():
        return ClickProvider() if requested == Payment.PROVIDER_CLICK else PaymeProvider()
    if payments_stub_active():
        return StubProvider()
    raise PaymentsUnavailable('Онлайн-оплата временно недоступна. Выберите оплату наличными.')

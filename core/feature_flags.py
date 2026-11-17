"""
Флаги, которые включают и выключают целые части продукта.

DEAL_FLOW_ENABLED — сделка через платформу: оформление и оплата брони, эскроу,
залог и кошелёк, споры, торг (он задаёт цену сделки), комиссия, отзывы по
сделке. Rentoo перешёл на доску объявлений с платными тарифами (16.11.2026), и
по умолчанию всё это выключено, но не удалено: модели, данные и код остаются,
флаг возвращает их без миграций.

При выключенном флаге эндпоинты сделки отвечают 410 `DEAL_FLOW_DISABLED`, а
периодические задачи по сделкам выходят, ничего не делая.
"""
import functools
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException

logger = logging.getLogger('core.feature_flags')


def deal_flow_enabled() -> bool:
    return bool(getattr(settings, 'DEAL_FLOW_ENABLED', False))


class DealFlowDisabled(APIException):
    status_code = status.HTTP_410_GONE
    default_detail = 'Сделки через платформу отключены: свяжитесь с владельцем в чате или по телефону.'
    default_code = 'DEAL_FLOW_DISABLED'

    def __init__(self):
        super().__init__()
        # Формат ошибок проекта — {code, detail}; code ставится до обработчика,
        # чтобы core.exceptions не заменил его общим 'error'.
        self.detail = {'code': self.default_code, 'detail': self.default_detail}


class DealFlowRequiredMixin:
    """Для APIView: при выключенном флаге — 410 до проверки прав и разбора тела."""

    def initial(self, request, *args, **kwargs):
        if not deal_flow_enabled():
            raise DealFlowDisabled()
        return super().initial(request, *args, **kwargs)


def skip_unless_deal_flow(task_func):
    """Для задач Celery по сделкам: при выключенном флаге задача ничего не делает."""

    @functools.wraps(task_func)
    def wrapper(*args, **kwargs):
        if not deal_flow_enabled():
            logger.info('%s skipped: DEAL_FLOW_ENABLED is off', task_func.__name__)
            return None
        return task_func(*args, **kwargs)

    return wrapper

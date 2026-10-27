"""
Режимы заглушек оплаты и MyID и где они разрешены.

Заглушка подтверждает оплату или личность без денег и без документов. Это
нужно для разработки и стенда, но на боевом сервере превращается в бесплатные
сделки, поэтому правило проверяется дважды: при старте (validate_runtime_modes
из AppConfig.ready — сервер, воркер и manage.py не поднимутся) и в момент
самого подтверждения (stub_allowed), на случай если настройки поменяли на лету.
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

APP_ENVS = ('dev', 'staging', 'prod')
PAYMENTS_MODES = ('off', 'stub', 'live')
MYID_MODES = ('off', 'stub')


def stub_allowed() -> bool:
    """Заглушки разрешены на стенде и при локальной разработке с DEBUG."""
    if settings.APP_ENV == 'staging':
        return True
    return settings.APP_ENV == 'dev' and bool(settings.DEBUG)


def payments_stub_active() -> bool:
    return settings.PAYMENTS_MODE == 'stub' and stub_allowed()


def payments_live() -> bool:
    return settings.PAYMENTS_MODE == 'live'


def myid_stub_active() -> bool:
    return settings.MYID_MODE == 'stub' and stub_allowed()


def validate_runtime_modes():
    """Бросает ImproperlyConfigured, если режимы недопустимы для окружения."""
    if settings.APP_ENV not in APP_ENVS:
        raise ImproperlyConfigured(
            f'APP_ENV={settings.APP_ENV!r}: допустимо одно из {", ".join(APP_ENVS)}.'
        )
    if settings.PAYMENTS_MODE not in PAYMENTS_MODES:
        raise ImproperlyConfigured(
            f'PAYMENTS_MODE={settings.PAYMENTS_MODE!r}: допустимо одно из {", ".join(PAYMENTS_MODES)}.'
        )
    if settings.MYID_MODE not in MYID_MODES:
        raise ImproperlyConfigured(
            f'MYID_MODE={settings.MYID_MODE!r}: допустимо одно из {", ".join(MYID_MODES)} '
            '(интеграции с MyID пока нет).'
        )
    if settings.PAYMENTS_MODE == 'stub' and not stub_allowed():
        raise ImproperlyConfigured(
            f'PAYMENTS_MODE=stub запрещён при APP_ENV={settings.APP_ENV} '
            f'(DEBUG={settings.DEBUG}): заглушка подтверждает оплату без денег. '
            'Используйте off или live.'
        )
    if settings.MYID_MODE == 'stub' and not stub_allowed():
        raise ImproperlyConfigured(
            f'MYID_MODE=stub запрещён при APP_ENV={settings.APP_ENV} '
            f'(DEBUG={settings.DEBUG}): заглушка подтверждает личность без документов.'
        )

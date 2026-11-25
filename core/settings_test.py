"""
Настройки для тестов: python manage.py test --settings=core.settings_test

Нужен только PostgreSQL (тесты гонок опираются на select_for_update, SQLite
их не проверит). Redis не нужен: кэш, channel layer и Celery — в памяти.
"""
from .settings import *  # noqa: F401,F403

# Стенд: заглушки оплаты и MyID разрешены, как на staging. Тесты на запрет в
# prod переопределяют APP_ENV/PAYMENTS_MODE сами.
APP_ENV = 'staging'
PAYMENTS_MODE = 'stub'
MYID_MODE = 'stub'
# Тесты сделки (блоки 1–2) идут со включённой сделкой; поведение при
# выключенном флаге проверяет apps/bookings/test_deal_flow_flag.py.
DEAL_FLOW_ENABLED = True
# Акция «PRO при регистрации» выключена: тесты ждут новых пользователей на FREE.
# Саму акцию проверяет apps/billing/test_promo.py (override_settings).
PROMO_FREE_PRO_UNTIL = ''

CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
TELEGRAM_BOT_TOKEN = ''
VAPID_PRIVATE_KEY = ''
USE_S3 = False
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

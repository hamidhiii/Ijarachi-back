"""
Django settings for Rentoo backend.
"""

from pathlib import Path
from decouple import config
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-me-in-production')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,169.58.192.146,back.rentoo.uz').split(',')

# Для POST с формы (вход в /admin/) Django сверяет заголовок Origin со схемой и хостом
# самого запроса. За nginx с TLS-терминацией Django видит голый http и ждёт
# http://back.rentoo.uz, а браузер шлёт https:// — отсюда 403 «CSRF verification failed».
CSRF_TRUSTED_ORIGINS = [
    origin for origin in config(
        'CSRF_TRUSTED_ORIGINS',
        default='https://back.rentoo.uz,https://ijarachi-front.vercel.app',
    ).split(',')
    if origin
]

# Включать только если nginx сам выставляет X-Forwarded-Proto и не пропускает его
# от клиента: иначе любой сможет выдать http-запрос за https.
if config('USE_X_FORWARDED_PROTO', default=False, cast=bool):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# ─── Apps ────────────────────────────────────────────────────────────────────

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',
    'mptt',
    'drf_spectacular',
    'phonenumber_field',
    'channels',
    'storages',

    # Celery beat
    'django_celery_beat',

    # Project apps
    'apps.users',
    'apps.catalog',
    'apps.bookings',
    'apps.payments',
    'apps.chat',
    'apps.notifications',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = 'core.asgi.application'

# ─── Database ─────────────────────────────────────────────────────────────────

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='rentoo'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default='postgres'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# ─── Auth ─────────────────────────────────────────────────────────────────────

AUTH_USER_MODEL = 'users.CustomUser'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ),
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.ScopedRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'auth': '10/min',
        'sms': '5/min',
        'payments': '20/min',
        'kyc': '10/min',
    },
    # Exactly one reverse proxy (nginx) sits in front of Django here. Without
    # this, SimpleRateThrottle.get_ident() falls back to hashing the raw
    # X-Forwarded-For string, which a client can pad with fake leading hops to
    # get a fresh throttle identity on every request.
    'NUM_PROXIES': 1,
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(
        minutes=config('JWT_ACCESS_TOKEN_LIFETIME_MINUTES', default=15, cast=int)
    ),
    'REFRESH_TOKEN_LIFETIME': timedelta(
        days=config('JWT_REFRESH_TOKEN_LIFETIME_DAYS', default=30, cast=int)
    ),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'SIGNING_KEY': config('JWT_SIGNING_KEY', default=SECRET_KEY),
}

# ─── CORS ─────────────────────────────────────────────────────────────────────

CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:3000,http://localhost:5173,https://ijarachi-front.vercel.app'
).split(',')
# Vercel preview deployments (per-branch and per-commit URLs) — matches e.g.
# https://ijarachi-front-git-feature-x-user.vercel.app and
# https://ijarachi-front-<hash>-user.vercel.app without listing each one.
CORS_ALLOWED_ORIGIN_REGEXES = [
    pattern for pattern in config('CORS_ALLOWED_ORIGIN_REGEXES', default=r'^https://ijarachi-front(-[a-zA-Z0-9-]+)?\.vercel\.app$').split(',')
    if pattern
]
CORS_ALLOW_CREDENTIALS = True

if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True

# ─── Redis & Celery ───────────────────────────────────────────────────────────

REDIS_URL = config('REDIS_URL', default='redis://localhost:6379/0')

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [REDIS_URL],
        },
    },
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Tashkent'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

from celery.schedules import crontab
CELERY_BEAT_SCHEDULE = {
    'notify-expiring-bookings-daily': {
        'task': 'apps.bookings.tasks.notify_expiring_bookings',
        'schedule': crontab(hour=9, minute=0),
    },
}

# ─── Media & Static ───────────────────────────────────────────────────────────

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# S3-совместимое объектное хранилище (Backblaze B2, Yandex Object Storage и т.п.).
# Включённый USE_S3 уводит в бакет все ImageField/FileField проекта: фото
# объявлений, аватары, вложения чата, фото сделок и документы KYC.
USE_S3 = config('USE_S3', default=False, cast=bool)
if USE_S3:
    AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID', default='')
    AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY', default='')
    AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME', default='')
    AWS_S3_ENDPOINT_URL = config('AWS_S3_ENDPOINT_URL', default='')
    AWS_S3_REGION_NAME = config('AWS_S3_REGION_NAME', default='us-west-004')
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    # B2 не принимает S3-заголовок x-amz-acl — с ACL по умолчанию загрузка падает
    AWS_DEFAULT_ACL = None
    # не затирать чужой файл при совпадении имени, а дописывать суффикс
    AWS_S3_FILE_OVERWRITE = False
    AWS_S3_OBJECT_PARAMETERS = {
        'CacheControl': f"max-age={config('AWS_S3_CACHE_MAX_AGE', default=86400, cast=int)}",
    }
    # Публичный бакет — постоянные прямые ссылки. Приватный (по умолчанию) — временные
    # подписанные ссылки: в media лежат паспорта и селфи KYC, их нельзя отдавать
    # по угадываемому URL. Публичным бакет имеет смысл делать только под фото объявлений.
    AWS_S3_PUBLIC_MEDIA = config('AWS_S3_PUBLIC_MEDIA', default=False, cast=bool)
    AWS_QUERYSTRING_AUTH = not AWS_S3_PUBLIC_MEDIA
    AWS_QUERYSTRING_EXPIRE = config('AWS_S3_URL_EXPIRE_SECONDS', default=3600, cast=int)
    if AWS_S3_PUBLIC_MEDIA and config('AWS_S3_CUSTOM_DOMAIN', default=''):
        # CDN/собственный домен перед бакетом; с подписанными ссылками несовместим
        AWS_S3_CUSTOM_DOMAIN = config('AWS_S3_CUSTOM_DOMAIN')

    STORAGES = {
        'default': {'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage'},
        # статика остаётся на диске и раздаётся whitenoise
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }

# ─── Internationalization ─────────────────────────────────────────────────────

LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Asia/Tashkent'
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─── Eskiz.uz SMS ─────────────────────────────────────────────────────────────

ESKIZ_EMAIL = config('ESKIZ_EMAIL', default='')
ESKIZ_PASSWORD = config('ESKIZ_PASSWORD', default='')
ESKIZ_BASE_URL = config('ESKIZ_BASE_URL', default='https://notify.eskiz.uz/api')
ESKIZ_SENDER_ID = config('ESKIZ_SENDER_ID', default='4546')
SMS_REQUEST_TIMEOUT_SECONDS = config('SMS_REQUEST_TIMEOUT_SECONDS', default=10, cast=int)

# Собственный KYC (паспорт/ID-карта + сверка лица), заменяет стороннюю MyID-интеграцию
KYC_FIRST_DEAL_COST = config('KYC_FIRST_DEAL_COST', default=8000, cast=int)
# face_recognition distance threshold: чем меньше — тем строже сверка лица с документом (0..1)
KYC_FACE_MATCH_DISTANCE = config('KYC_FACE_MATCH_DISTANCE', default=0.5, cast=float)
# Минимальный перепад Eye Aspect Ratio между кадрами, чтобы засчитать моргание
KYC_LIVENESS_EAR_DELTA = config('KYC_LIVENESS_EAR_DELTA', default=0.05, cast=float)
# Минимальное относительное смещение центра лица между кадрами (к ширине лица), чтобы засчитать поворот головы
KYC_LIVENESS_MOVEMENT_RATIO = config('KYC_LIVENESS_MOVEMENT_RATIO', default=0.08, cast=float)


# ─── Payment Providers ────────────────────────────────────────────────────────

PAYME_MERCHANT_ID = config('PAYME_MERCHANT_ID', default='')
PAYME_SECRET_KEY = config('PAYME_SECRET_KEY', default='')

CLICK_SERVICE_ID = config('CLICK_SERVICE_ID', default='')
CLICK_MERCHANT_ID = config('CLICK_MERCHANT_ID', default='')
CLICK_SECRET_KEY = config('CLICK_SECRET_KEY', default='')

# Platform commission (%)
PLATFORM_COMMISSION_PERCENT = config('PLATFORM_COMMISSION_PERCENT', default=10, cast=int)

# OTP settings
OTP_EXPIRY_SECONDS = config('OTP_EXPIRY_SECONDS', default=120, cast=int)
OTP_RESEND_COOLDOWN_SECONDS = config('OTP_RESEND_COOLDOWN_SECONDS', default=60, cast=int)

# ─── Telegram OTP-бот (временная замена SMS) ──────────────────────────────────

TELEGRAM_BOT_TOKEN = config('TELEGRAM_BOT_TOKEN', default='')
TELEGRAM_BOT_USERNAME = config('TELEGRAM_BOT_USERNAME', default='')
TELEGRAM_API_BASE_URL = config('TELEGRAM_API_BASE_URL', default='https://api.telegram.org')
# Секрет в пути вебхука (/api/v1/telegram/webhook/<secret>/), защищает от посторонних запросов
TELEGRAM_WEBHOOK_SECRET = config('TELEGRAM_WEBHOOK_SECRET', default='')
# Если код не удалось отправить в Telegram (или номер ещё не привязан к боту) — падать в SMS
OTP_SMS_FALLBACK_ENABLED = config('OTP_SMS_FALLBACK_ENABLED', default=False, cast=bool)

# Mobile app deep-link scheme (rentoo://...)
APP_DEEPLINK_SCHEME = config('APP_DEEPLINK_SCHEME', default='rentoo')

# ─── Swagger/Redoc ────────────────────────────────────────────────────────────

SPECTACULAR_SETTINGS = {
    'TITLE': 'Rentoo API',
    'DESCRIPTION': 'P2P rental backend for Rentoo.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
}

# ─── Logging ──────────────────────────────────────────────────────────────────

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {module} — {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'apps.payments': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps.bookings': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps.notifications': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

from django.apps import AppConfig


class BookingsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.bookings'
    verbose_name = 'Бронирования'

    def ready(self):
        from . import signals  # noqa: F401  — регистрирует запись истории статусов

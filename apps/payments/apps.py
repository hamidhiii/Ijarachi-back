from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.payments'
    verbose_name = 'Платежи'

    def ready(self):
        # Заглушка оплаты в prod — сервер не должен стартовать вовсе.
        from core.runtime_modes import validate_runtime_modes
        validate_runtime_modes()

import base64

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Генерирует пару VAPID-ключей для Web Push. Приватный ключ — в .env как '
        'VAPID_PRIVATE_KEY (секрет, остаётся на сервере), публичный — VAPID_PUBLIC_KEY '
        '(не секрет, его отдают фронту для подписки браузера).'
    )

    def handle(self, *args, **options):
        from py_vapid import Vapid01
        from cryptography.hazmat.primitives import serialization

        vapid = Vapid01()
        vapid.generate_keys()

        private_numbers = vapid.private_key.private_numbers()
        raw_private = private_numbers.private_value.to_bytes(32, 'big')
        private_b64 = base64.urlsafe_b64encode(raw_private).rstrip(b'=').decode('ascii')

        public_raw = vapid.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        public_b64 = base64.urlsafe_b64encode(public_raw).rstrip(b'=').decode('ascii')

        self.stdout.write(self.style.SUCCESS('Добавь в .env на сервере:'))
        self.stdout.write(f'VAPID_PRIVATE_KEY={private_b64}')
        self.stdout.write(f'VAPID_PUBLIC_KEY={public_b64}')
        self.stdout.write('')
        self.stdout.write('VAPID_PUBLIC_KEY — не секрет, отдай его фронту для applicationServerKey.')

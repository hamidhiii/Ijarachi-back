import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        'Registers (or removes with --delete) the Telegram webhook for the OTP bot. '
        'Requires TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET in settings.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--base-url', required=False,
            help='Public HTTPS base URL of the backend, e.g. https://api.rentoo.uz',
        )
        parser.add_argument('--delete', action='store_true', help='Remove the webhook instead of setting it')

    def _redact(self, text: str) -> str:
        # requests' HTTPError embeds the full request URL, which contains the bot
        # token for the Telegram Bot API — strip it before it hits stdout/logs.
        token = settings.TELEGRAM_BOT_TOKEN
        return text.replace(token, '***') if token else text

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError('TELEGRAM_BOT_TOKEN is not set')

        api = f'{settings.TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}'

        if options['delete']:
            try:
                resp = requests.post(f'{api}/deleteWebhook', timeout=10)
                resp.raise_for_status()
            except Exception as exc:
                raise CommandError(self._redact(str(exc)))
            self.stdout.write(self.style.SUCCESS(f'Webhook removed: {resp.json()}'))
            return

        base_url = options.get('base_url')
        if not base_url:
            raise CommandError('--base-url is required to set the webhook')
        if not settings.TELEGRAM_WEBHOOK_SECRET:
            raise CommandError('TELEGRAM_WEBHOOK_SECRET is not set')

        url = f'{base_url.rstrip("/")}/api/v1/telegram/webhook/{settings.TELEGRAM_WEBHOOK_SECRET}/'
        try:
            resp = requests.post(f'{api}/setWebhook', data={
                'url': url,
                'allowed_updates': '["message"]',
            }, timeout=10)
            resp.raise_for_status()
        except Exception as exc:
            raise CommandError(self._redact(str(exc)))
        self.stdout.write(self.style.SUCCESS(f'Webhook set to {url}: {resp.json()}'))

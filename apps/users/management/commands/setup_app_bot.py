from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.users import telegram_app_bot as app_bot


class Command(BaseCommand):
    help = (
        'Sets up @rentoo_app (the Mini App bot): its description and short description '
        '(uz by default, ru for Russian-language users) and the webhook that answers /start '
        'with a welcome. Requires TELEGRAM_WEBAPP_BOT_TOKEN.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--base-url', required=True,
            help='Public HTTPS base URL of the backend, e.g. https://back.rentoo.uz',
        )

    def _call(self, method, payload):
        result = app_bot.api(method, payload)
        if not result.get('ok'):
            raise CommandError(f'{method}: {result.get("description")}')
        self.stdout.write(f'{method} {payload.get("language_code", "")}: ok')

    def handle(self, *args, **options):
        if not app_bot.token():
            raise CommandError('TELEGRAM_WEBAPP_BOT_TOKEN is not set')
        base_url = options['base_url'].rstrip('/')
        if not base_url.startswith('https://'):
            raise CommandError('--base-url must be https://')

        # No language_code = the default every user sees unless their Telegram
        # is in Russian.
        for lang, code in (('uz', ''), ('ru', 'ru')):
            extra = {'language_code': code} if code else {}
            self._call('setMyDescription', {'description': app_bot.DESCRIPTION[lang], **extra})
            self._call('setMyShortDescription', {'short_description': app_bot.SHORT_DESCRIPTION[lang], **extra})

        url = f'{base_url}/api/v1/telegram/webhook/app/'
        self._call('setWebhook', {
            'url': url,
            'secret_token': app_bot.webhook_secret(),
            'allowed_updates': ['message'],
            'drop_pending_updates': True,
        })
        self.stdout.write(self.style.SUCCESS(f'@rentoo_app ready, webhook → {url}'))

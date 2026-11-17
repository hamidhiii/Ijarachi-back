from django.core.management.base import BaseCommand, CommandError

from apps.crm import telegram as bot

DESCRIPTION = {
    'uz': (
        "Rentoo prokatlari uchun CRM bot.\n"
        "Ertalab — bugun kimga berish va kimdan qaytarib olish. Bir tugma bilan: "
        "berildi, qaytarildi, ko'chirish.\n\n"
        "Ulash: owner.rentoo.uz kabinetida «Telegram'ni ulash»."
    ),
    'ru': (
        'CRM-бот для прокатов Rentoo.\n'
        'Утром — кому сегодня выдать и у кого забрать. В одну кнопку: '
        'выдано, принято, перенести.\n\n'
        'Подключение: «Подключить Telegram» в кабинете owner.rentoo.uz.'
    ),
}
SHORT = {
    'uz': 'Rentoo prokatlari uchun CRM: bugungi berish va qaytarishlar tugmalar bilan.',
    'ru': 'CRM для прокатов Rentoo: выдачи и возвраты на сегодня — кнопками.',
}
COMMANDS = {
    'uz': [{'command': 'bugun', 'description': 'Bugungi berish va qaytarishlar'}],
    'ru': [{'command': 'bugun', 'description': 'Выдачи и возвраты на сегодня'}],
}


class Command(BaseCommand):
    help = (
        'Sets up the CRM bot (CRM_BOT_TOKEN): description, /bugun command and the webhook '
        'for messages and button presses.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--base-url', required=True, help='Public HTTPS backend URL, e.g. https://back.rentoo.uz')

    def _call(self, method, payload):
        if bot.api(method, payload) is None:
            raise CommandError(f'{method} failed — see the log')
        self.stdout.write(f'{method} {payload.get("language_code", "")}: ok')

    def handle(self, *args, **options):
        if not bot.token():
            raise CommandError('CRM_BOT_TOKEN is not set')
        base_url = options['base_url'].rstrip('/')
        if not base_url.startswith('https://'):
            raise CommandError('--base-url must be https://')

        for lang, code in (('uz', ''), ('ru', 'ru')):
            extra = {'language_code': code} if code else {}
            self._call('setMyDescription', {'description': DESCRIPTION[lang], **extra})
            self._call('setMyShortDescription', {'short_description': SHORT[lang], **extra})
            self._call('setMyCommands', {'commands': COMMANDS[lang], **extra})

        url = f'{base_url}/api/v1/telegram/webhook/crm/'
        self._call('setWebhook', {
            'url': url,
            'secret_token': bot.webhook_secret(),
            'allowed_updates': ['message', 'callback_query'],
            'drop_pending_updates': True,
        })
        self.stdout.write(self.style.SUCCESS(f'CRM bot ready, webhook → {url}'))

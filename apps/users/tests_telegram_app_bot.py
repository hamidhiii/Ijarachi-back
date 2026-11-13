from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.users import telegram_app_bot as app_bot

URL = '/api/v1/telegram/webhook/app/'


def update(text='/start', lang='uz', chat_type='private'):
    return {
        'update_id': 1,
        'message': {
            'message_id': 1,
            'from': {'id': 42, 'is_bot': False, 'first_name': 'Ali', 'language_code': lang},
            'chat': {'id': 42, 'type': chat_type},
            'text': text,
        },
    }


@override_settings(TELEGRAM_WEBAPP_BOT_TOKEN='222:app-bot', FRONTEND_BASE_URL='https://rentoo.uz')
class AppBotWebhookTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.headers = {'HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN': app_bot.webhook_secret()}

    @mock.patch('apps.users.telegram_app_bot.api', return_value={'ok': True})
    def test_start_gets_welcome_with_mini_app_button(self, api):
        response = self.client.post(URL, update(), format='json', **self.headers)
        self.assertEqual(response.status_code, 200)
        method, payload = api.call_args.args
        self.assertEqual(method, 'sendMessage')
        self.assertEqual(payload['chat_id'], 42)
        self.assertIn("xush kelibsiz", payload['text'])
        button = payload['reply_markup']['inline_keyboard'][0][0]
        self.assertEqual(button['web_app']['url'], 'https://rentoo.uz/')

    @mock.patch('apps.users.telegram_app_bot.api', return_value={'ok': True})
    def test_russian_user_gets_russian(self, api):
        self.client.post(URL, update(lang='ru'), format='json', **self.headers)
        self.assertIn('Добро пожаловать', api.call_args.args[1]['text'])

    @mock.patch('apps.users.telegram_app_bot.api', return_value={'ok': True})
    def test_wrong_secret_is_404(self, api):
        response = self.client.post(
            URL, update(), format='json', HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='nope'
        )
        self.assertEqual(response.status_code, 404)
        api.assert_not_called()

    @mock.patch('apps.users.telegram_app_bot.api', return_value={'ok': True})
    def test_group_messages_are_ignored(self, api):
        response = self.client.post(URL, update(chat_type='group'), format='json', **self.headers)
        self.assertEqual(response.status_code, 200)
        api.assert_not_called()

    def test_texts_fit_telegram_limits(self):
        for lang in ('uz', 'ru'):
            self.assertLessEqual(len(app_bot.DESCRIPTION[lang]), 512)
            self.assertLessEqual(len(app_bot.SHORT_DESCRIPTION[lang]), 120)


@override_settings(TELEGRAM_WEBAPP_BOT_TOKEN='')
class AppBotUnconfiguredTests(TestCase):
    def test_no_token_no_webhook(self):
        response = APIClient().post(URL, update(), format='json', HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='')
        self.assertEqual(response.status_code, 404)

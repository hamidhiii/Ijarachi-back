import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.users.models import CustomUser, TelegramLink
from apps.users.telegram_webapp import verify_init_data

TOKEN = '123456:TEST-token'


def sign(fields: dict, token: str = TOKEN) -> str:
    """initData exactly as Telegram builds it: sorted key=value lines, HMAC'd."""
    check = '\n'.join(f'{k}={fields[k]}' for k in sorted(fields))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, 'hash': digest})


def init_data(user_id=42, auth_date=None, **extra):
    fields = {
        'query_id': 'AAE',
        'user': json.dumps({'id': user_id, 'first_name': 'Ali', 'username': 'ali', 'language_code': 'uz'}),
        'auth_date': str(int(time.time() if auth_date is None else auth_date)),
        'signature': 'ed25519-sig',
        **extra,
    }
    return sign(fields)


class VerifyInitDataTests(TestCase):
    def test_genuine(self):
        user = verify_init_data(init_data(), bot_token=TOKEN)
        self.assertIsNotNone(user)
        self.assertEqual(user.id, 42)
        self.assertEqual(user.language_code, 'uz')

    def test_other_bots_token(self):
        self.assertIsNone(verify_init_data(init_data(), bot_token='999:other'))

    def test_tampered_user(self):
        data = init_data().replace('%22id%22%3A+42', '%22id%22%3A+43')
        self.assertIsNone(verify_init_data(data, bot_token=TOKEN))

    def test_expired(self):
        self.assertIsNone(verify_init_data(init_data(auth_date=time.time() - 2 * 86400), bot_token=TOKEN))

    def test_from_the_future(self):
        self.assertIsNone(verify_init_data(init_data(auth_date=time.time() + 3600), bot_token=TOKEN))

    def test_duplicate_key(self):
        self.assertIsNone(verify_init_data(init_data() + '&user=x', bot_token=TOKEN))

    def test_garbage(self):
        for data in ('', 'hash=', 'nonsense', 'a=1&hash=00'):
            self.assertIsNone(verify_init_data(data, bot_token=TOKEN))

    def test_no_bot_token(self):
        self.assertIsNone(verify_init_data(init_data(), bot_token=''))

    @override_settings(TELEGRAM_BOT_TOKEN='111:otp-bot', TELEGRAM_WEBAPP_BOT_TOKEN=TOKEN)
    def test_signed_by_the_mini_app_bot(self):
        self.assertIsNotNone(verify_init_data(init_data()))

    @override_settings(TELEGRAM_BOT_TOKEN=TOKEN, TELEGRAM_WEBAPP_BOT_TOKEN='222:app-bot')
    def test_signed_by_the_otp_bot(self):
        self.assertIsNotNone(verify_init_data(init_data()))

    @override_settings(TELEGRAM_BOT_TOKEN='111:otp-bot', TELEGRAM_WEBAPP_BOT_TOKEN='222:app-bot')
    def test_signed_by_neither(self):
        self.assertIsNone(verify_init_data(init_data()))


@override_settings(TELEGRAM_BOT_TOKEN='111:otp-bot', TELEGRAM_WEBAPP_BOT_TOKEN=TOKEN)
class TelegramWebAppLoginTests(TestCase):
    url = '/api/v1/auth/telegram/'

    def setUp(self):
        cache.clear()  # throttle counters
        self.client = APIClient()

    def test_linked_account_signs_in(self):
        TelegramLink.objects.create(phone='+998901234567', chat_id=42, telegram_user_id=42)
        response = self.client.post(self.url, {'init_data': init_data()}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn('access', response.data)
        self.assertTrue(response.data['is_new_user'])
        self.assertTrue(CustomUser.objects.filter(phone='+998901234567').exists())

    def test_existing_user_is_not_new(self):
        CustomUser.objects.create(phone='+998901234567')
        TelegramLink.objects.create(phone='+998901234567', chat_id=42, telegram_user_id=42)
        response = self.client.post(self.url, {'init_data': init_data()}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['is_new_user'])

    def test_legacy_link_without_user_id(self):
        TelegramLink.objects.create(phone='+998901234567', chat_id=42, telegram_user_id=None)
        response = self.client.post(self.url, {'init_data': init_data()}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_someone_elses_link_is_not_used(self):
        TelegramLink.objects.create(phone='+998901234567', chat_id=7, telegram_user_id=7)
        response = self.client.post(self.url, {'init_data': init_data()}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['code'], 'telegram_not_linked')

    def test_forged_init_data(self):
        TelegramLink.objects.create(phone='+998901234567', chat_id=42, telegram_user_id=42)
        forged = init_data().rsplit('hash=', 1)[0] + 'hash=' + '0' * 64
        response = self.client.post(self.url, {'init_data': forged}, format='json')
        self.assertEqual(response.status_code, 401)

    def test_disabled_account(self):
        CustomUser.objects.create(phone='+998901234567', is_active=False)
        TelegramLink.objects.create(phone='+998901234567', chat_id=42, telegram_user_id=42)
        response = self.client.post(self.url, {'init_data': init_data()}, format='json')
        self.assertEqual(response.status_code, 403)

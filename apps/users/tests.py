"""Привязка Telegram-бота и заглушка MyID."""
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.bookings.testing import make_user
from apps.users.models import OTPCode, Profile, TelegramLink

SECRET = 'hook-secret'
SENDER_ID = 111
VICTIM_PHONE = '+998901234567'


@override_settings(TELEGRAM_WEBHOOK_SECRET=SECRET, TELEGRAM_BOT_TOKEN='')
class TelegramContactTests(APITestCase):
    url = reverse('telegram-webhook', kwargs={'secret': SECRET})

    def _send_contact(self, contact):
        update = {
            'message': {
                'chat': {'id': 555},
                'from': {'id': SENDER_ID, 'username': 'someone'},
                'contact': {'phone_number': '998901234567', **contact},
            },
        }
        return self.client.post(self.url, update, format='json')

    def test_contact_of_another_telegram_user_is_rejected(self):
        response = self._send_contact({'user_id': 999})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(TelegramLink.objects.exists())
        self.assertFalse(OTPCode.objects.exists())

    def test_contact_without_user_id_is_rejected(self):
        # Контакт из записной книжки: Telegram не знает, чей это номер.
        response = self._send_contact({})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(TelegramLink.objects.exists())
        self.assertFalse(OTPCode.objects.filter(phone=VICTIM_PHONE).exists())

    def test_foreign_contact_does_not_take_over_existing_link(self):
        TelegramLink.objects.create(phone=VICTIM_PHONE, chat_id=777, telegram_user_id=222)

        self._send_contact({})

        link = TelegramLink.objects.get(phone=VICTIM_PHONE)
        self.assertEqual(link.chat_id, 777)

    def test_own_contact_is_linked(self):
        response = self._send_contact({'user_id': SENDER_ID})

        self.assertEqual(response.status_code, 200)
        link = TelegramLink.objects.get(phone=VICTIM_PHONE)
        self.assertEqual(link.chat_id, 555)
        self.assertEqual(link.telegram_user_id, SENDER_ID)
        self.assertTrue(OTPCode.objects.filter(phone=VICTIM_PHONE).exists())


class MyIDStubTests(APITestCase):
    url = reverse('kyc-myid-stub-verify')

    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.client.force_authenticate(self.user)

    def test_stub_verifies_on_staging(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'approved')
        self.assertTrue(Profile.objects.get(user=self.user).is_verified_kyc)

    @override_settings(MYID_MODE='off')
    def test_stub_is_404_when_off(self):
        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.assertFalse(Profile.objects.filter(user=self.user, is_verified_kyc=True).exists())

    @override_settings(APP_ENV='prod', DEBUG=False)
    def test_stub_is_404_in_prod_even_if_mode_is_stub(self):
        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.assertFalse(Profile.objects.filter(user=self.user, is_verified_kyc=True).exists())

"""OTP: непредсказуемый код, лимит попыток; заблокированный пользователь."""
from unittest import mock

from asgiref.sync import async_to_sync
from django.core.cache import cache
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.bookings.testing import make_user
from apps.users.models import OTPCode, PhoneChangeRequest
from apps.users.sms import generate_otp
from core.ws_auth import _get_user_from_token

PHONE = '+998901112233'


class OTPGenerationTests(APITestCase):
    def test_code_comes_from_secrets(self):
        with mock.patch('apps.users.sms.secrets.choice', return_value='7') as choice:
            self.assertEqual(generate_otp(), '777777')
        self.assertEqual(choice.call_count, 6)


@override_settings(OTP_MAX_ATTEMPTS=3)
class OTPAttemptLimitTests(APITestCase):
    url = reverse('auth-verify-otp')

    def setUp(self):
        cache.clear()
        self.otp = OTPCode.objects.create(phone=PHONE, code='123456')

    def _verify(self, code):
        return self.client.post(self.url, {'phone': PHONE, 'code': code}, format='json')

    def test_right_code_logs_in(self):
        response = self._verify('123456')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('access', response.data)

    def test_code_dies_after_max_wrong_attempts(self):
        self.assertEqual(self._verify('000000').data['code'], 'otp_invalid')
        self.assertEqual(self._verify('000001').data['code'], 'otp_invalid')
        third = self._verify('000002')
        self.assertEqual(third.data['code'], 'otp_attempts_exceeded')

        # Даже верный код больше не принимается — нужен новый.
        response = self._verify('123456')
        self.assertEqual(response.status_code, 400)
        self.otp.refresh_from_db()
        self.assertTrue(self.otp.is_used)
        self.assertEqual(self.otp.attempts, 3)

    def test_wrong_attempts_below_limit_keep_code_alive(self):
        self._verify('000000')
        self.assertEqual(self._verify('123456').status_code, 200)

    def test_used_code_cannot_be_reused(self):
        self._verify('123456')
        self.assertEqual(self._verify('123456').status_code, 400)


@override_settings(OTP_MAX_ATTEMPTS=2)
class PhoneChangeAttemptLimitTests(APITestCase):
    def test_phone_change_code_dies_after_limit(self):
        cache.clear()
        user = make_user()
        PhoneChangeRequest.objects.create(user=user, new_phone=PHONE, code='123456')
        self.client.force_authenticate(user)
        url = reverse('auth-phone-change-verify')

        self.client.post(url, {'new_phone': PHONE, 'code': '000000'}, format='json')
        self.client.post(url, {'new_phone': PHONE, 'code': '000001'}, format='json')
        response = self.client.post(url, {'new_phone': PHONE, 'code': '123456'}, format='json')

        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertNotEqual(user.phone, PHONE)


class BlockedUserTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.staff = make_user(is_staff=True)

    def test_blocked_user_gets_no_tokens(self):
        self.user.is_active = False
        self.user.save()
        OTPCode.objects.create(phone=self.user.phone, code='123456')

        response = self.client.post(
            reverse('auth-verify-otp'), {'phone': self.user.phone, 'code': '123456'}, format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['code'], 'user_blocked')
        self.assertNotIn('access', response.data)

    def test_blocked_user_cannot_refresh(self):
        refresh = RefreshToken.for_user(self.user)
        self.user.is_active = False
        self.user.save()

        response = self.client.post(reverse('auth-token-refresh'), {'refresh': str(refresh)}, format='json')

        self.assertEqual(response.status_code, 401)

    def test_active_user_can_refresh(self):
        refresh = RefreshToken.for_user(self.user)
        response = self.client.post(reverse('auth-token-refresh'), {'refresh': str(refresh)}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def test_admin_block_revokes_refresh_tokens(self):
        refresh = RefreshToken.for_user(self.user)
        self.client.force_authenticate(self.staff)

        response = self.client.patch(
            reverse('admin-user-status', kwargs={'pk': self.user.pk}), {'status': 'blocked'}, format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        # Разблокировали обратно — старый refresh всё равно погашен.
        self.client.patch(reverse('admin-user-status', kwargs={'pk': self.user.pk}), {'status': 'active'}, format='json')
        self.client.force_authenticate(None)
        response = self.client.post(reverse('auth-token-refresh'), {'refresh': str(refresh)}, format='json')
        self.assertEqual(response.status_code, 401)


class BlockedUserWebSocketTests(TransactionTestCase):
    def test_blocked_user_is_anonymous_on_websocket(self):
        user = make_user()
        token = str(RefreshToken.for_user(user).access_token)

        self.assertEqual(async_to_sync(_get_user_from_token)(token).pk, user.pk)

        user.is_active = False
        user.save()
        self.assertFalse(async_to_sync(_get_user_from_token)(token).is_authenticated)

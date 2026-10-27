"""Заглушка оплаты, режимы PAYMENTS_MODE и запрет заглушек в prod."""
import os
import subprocess
import sys
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.bookings.models import Booking
from apps.bookings.testing import make_booking, make_item, make_user
from apps.payments.models import Payment
from apps.payments.providers import PaymentsUnavailable, StubProvider
from core.runtime_modes import validate_runtime_modes

PROD = dict(APP_ENV='prod', DEBUG=False)


class RuntimeModeValidationTests(SimpleTestCase):
    @override_settings(PAYMENTS_MODE='stub', MYID_MODE='off', **PROD)
    def test_payments_stub_in_prod_is_refused(self):
        with self.assertRaisesMessage(ImproperlyConfigured, 'PAYMENTS_MODE=stub'):
            validate_runtime_modes()

    @override_settings(PAYMENTS_MODE='stub', MYID_MODE='off', **PROD)
    def test_payments_app_refuses_to_start_with_stub_in_prod(self):
        with self.assertRaises(ImproperlyConfigured):
            apps.get_app_config('payments').ready()

    @override_settings(PAYMENTS_MODE='stub', MYID_MODE='off', APP_ENV='dev', DEBUG=False)
    def test_payments_stub_in_dev_without_debug_is_refused(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_runtime_modes()

    @override_settings(PAYMENTS_MODE='off', MYID_MODE='stub', **PROD)
    def test_myid_stub_in_prod_is_refused(self):
        with self.assertRaisesMessage(ImproperlyConfigured, 'MYID_MODE=stub'):
            validate_runtime_modes()

    @override_settings(PAYMENTS_MODE='live', MYID_MODE='live', APP_ENV='staging')
    def test_myid_live_is_not_supported_yet(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_runtime_modes()

    @override_settings(PAYMENTS_MODE='stub', MYID_MODE='stub', APP_ENV='staging', DEBUG=False)
    def test_stubs_allowed_on_staging(self):
        validate_runtime_modes()

    @override_settings(PAYMENTS_MODE='stub', MYID_MODE='stub', APP_ENV='dev', DEBUG=True)
    def test_stubs_allowed_in_local_dev(self):
        validate_runtime_modes()

    @override_settings(PAYMENTS_MODE='live', MYID_MODE='off', **PROD)
    def test_live_payments_allowed_in_prod(self):
        validate_runtime_modes()


class ServerStartTests(SimpleTestCase):
    """Настоящий старт Django с боевыми настройками: со stub-ом он должен упасть."""

    def _manage_check(self, **env):
        base = Path(settings.BASE_DIR)
        full_env = {
            **os.environ,
            'DJANGO_SETTINGS_MODULE': 'core.settings',
            'SECRET_KEY': 'test',
            'DEBUG': 'False',
            'MYID_MODE': 'off',
            **env,
        }
        return subprocess.run(
            [sys.executable, str(base / 'manage.py'), 'check'],
            cwd=base, env=full_env, capture_output=True, text=True, timeout=120,
        )

    def test_prod_with_payments_stub_does_not_start(self):
        result = self._manage_check(APP_ENV='prod', PAYMENTS_MODE='stub')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('PAYMENTS_MODE=stub', result.stderr)

    def test_prod_without_explicit_mode_starts_with_payments_off(self):
        result = self._manage_check(APP_ENV='prod', PAYMENTS_MODE='off')
        self.assertEqual(result.returncode, 0, result.stderr)


class PaymentModeTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.renter = make_user()
        self.item = make_item(self.owner)
        self.draft = make_booking(self.item, self.renter)
        self.client.force_authenticate(self.renter)

    def _pay(self, provider):
        return self.client.post(reverse('deal-pay', kwargs={'pk': self.draft.pk}), {'provider': provider}, format='json')

    def test_stub_confirms_payment_on_staging(self):
        response = self._pay('click')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['provider'], Payment.PROVIDER_STUB)
        self.assertEqual(response.data['status'], Payment.STATUS_PAID)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Booking.STATUS_PAID)
        self.assertEqual(self.draft.escrow_status, Booking.ESCROW_HELD)

    @override_settings(PAYMENTS_MODE='off')
    def test_online_payment_unavailable_when_off(self):
        response = self._pay('payme')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'PAYMENT_METHOD_UNAVAILABLE')
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Booking.STATUS_DRAFT)
        self.assertFalse(Payment.objects.exists())

    @override_settings(PAYMENTS_MODE='off')
    def test_cash_works_when_online_is_off(self):
        response = self._pay('cash')

        self.assertEqual(response.status_code, 201, response.data)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Booking.STATUS_PENDING_PAYMENT)

    def test_stub_refuses_at_runtime_in_prod(self):
        # Настройки сменили после старта — заглушка всё равно не подтвердит оплату.
        payment = Payment.objects.create(booking=self.draft, provider=Payment.PROVIDER_STUB, amount=1)
        with override_settings(**PROD):
            with self.assertRaises(PaymentsUnavailable):
                StubProvider().start(payment)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.STATUS_PENDING)

    @override_settings(PAYMENTS_MODE='live')
    def test_live_mode_returns_provider_checkout(self):
        response = self._pay('payme')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['redirect_url'].startswith('https://checkout.paycom.uz/'))
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Booking.STATUS_PENDING_PAYMENT)


class WebhookGateTests(APITestCase):
    def test_webhooks_are_404_unless_live(self):
        for mode in ('off', 'stub'):
            with self.subTest(mode=mode), override_settings(PAYMENTS_MODE=mode):
                for name in ('payme-webhook', 'click-webhook', 'payme-callback', 'click-callback'):
                    response = self.client.post(reverse(name), {}, format='json')
                    self.assertEqual(response.status_code, 404, name)

    @override_settings(PAYMENTS_MODE='live', PAYME_SECRET_KEY='secret')
    def test_webhooks_reachable_when_live(self):
        response = self.client.post(reverse('payme-webhook'), {'method': 'CheckTransaction'}, format='json')
        # Без Basic-авторизации Payme — отказ самого обработчика, а не 404.
        self.assertEqual(response.status_code, 403)

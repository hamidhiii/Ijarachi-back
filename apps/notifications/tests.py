"""Web Push: подписка только на известные push-сервисы (защита от SSRF)."""
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.bookings.testing import make_user
from apps.notifications.models import Notification, PushSubscription
from apps.notifications.tasks import send_web_push

KEYS = {'p256dh': 'BKey', 'auth': 'secret'}


class PushEndpointTests(APITestCase):
    url = reverse('push-subscribe')

    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.client.force_authenticate(self.user)

    def _subscribe(self, endpoint):
        return self.client.post(self.url, {'endpoint': endpoint, 'keys': KEYS}, format='json')

    def test_known_push_services_are_accepted(self):
        for endpoint in (
            'https://fcm.googleapis.com/fcm/send/abc',
            'https://updates.push.services.mozilla.com/wpush/v2/abc',
            'https://web.push.apple.com/QGuQ',
            'https://wns2-par02p.notify.windows.com/w/?token=abc',
        ):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self._subscribe(endpoint).status_code, 201)

    def test_internal_and_foreign_endpoints_are_rejected(self):
        for endpoint in (
            'http://fcm.googleapis.com/fcm/send/abc',
            'https://169.254.169.254/latest/meta-data/',
            'https://localhost/admin/',
            'https://evil.example.com/fcm.googleapis.com',
            'https://fcm.googleapis.com.evil.example.com/x',
            'https://fcm.googleapis.com:6379/x',
        ):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self._subscribe(endpoint).status_code, 400)
        self.assertFalse(PushSubscription.objects.exists())

    @override_settings(VAPID_PRIVATE_KEY='key')
    def test_stored_untrusted_subscription_is_dropped_not_called(self):
        PushSubscription.objects.create(user=self.user, endpoint='http://10.0.0.1:6379/', **KEYS)
        notification = Notification.objects.create(user=self.user, type=Notification.TYPE_SYSTEM, payload={'title': 't'})

        with mock.patch('pywebpush.webpush') as webpush:
            send_web_push(notification.pk)

        webpush.assert_not_called()
        self.assertFalse(PushSubscription.objects.exists())

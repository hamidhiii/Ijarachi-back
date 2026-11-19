"""API монитора для monitor.rentoo.uz и пинг присутствия."""
from unittest import mock

from django.urls import reverse
from rest_framework.test import APITestCase

from apps.billing.models import Plan
from apps.billing.testing import give_plan
from apps.bookings.testing import make_item, make_user
from apps.monitoring.models import AuthEvent, MonitorAccess


class MonitorApiTests(APITestCase):
    def setUp(self):
        self.staff = make_user()
        self.staff.set_password('secret-pass-1')
        self.staff.save()
        MonitorAccess.objects.create(user=self.staff, can_view_payments=False)

    def login(self, user=None):
        self.client.force_authenticate(user or self.staff)

    def test_login_only_with_monitor_access(self):
        url = reverse('monitor-api-login')
        ok = self.client.post(url, {'phone': self.staff.phone, 'password': 'secret-pass-1'}, format='json')
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertTrue(ok.json()['access'])
        self.assertFalse(ok.json()['me']['can_view_payments'])

        stranger = make_user()
        stranger.set_password('secret-pass-1')
        stranger.save()
        denied = self.client.post(url, {'phone': stranger.phone, 'password': 'secret-pass-1'}, format='json')
        self.assertEqual(denied.status_code, 401)
        wrong = self.client.post(url, {'phone': self.staff.phone, 'password': 'nope'}, format='json')
        self.assertEqual(wrong.status_code, 401)

    def test_no_access_is_403(self):
        self.client.force_authenticate(make_user())
        self.assertEqual(self.client.get(reverse('monitor-api-overview')).status_code, 403)

    def test_overview_hides_money_without_payments_section(self):
        owner = make_user()
        give_plan(owner, Plan.START)
        make_item(owner)
        self.login()
        data = self.client.get(reverse('monitor-api-overview'), {'days': 30}).json()
        keys = {k['key'] for k in data['kpis']}
        self.assertIn('signups', keys)
        self.assertIn('paying', keys)
        self.assertNotIn('revenue', keys)
        self.assertNotIn('revenue', data['series'])
        self.assertEqual(len(data['series']['dates']), 30)
        self.assertEqual(next(k for k in data['kpis'] if k['key'] == 'paying')['value'], 1)

        MonitorAccess.objects.filter(user=self.staff).update(can_view_payments=True)
        self.client.force_authenticate(type(self.staff).objects.get(pk=self.staff.pk))
        data = self.client.get(reverse('monitor-api-overview')).json()
        self.assertIn('revenue', {k['key'] for k in data['kpis']})
        self.assertEqual(len(data['series']['revenue']), 7)

    def test_sections_and_lists(self):
        item = make_item(make_user())
        item.title = 'Шатёр'
        item.save()
        self.login()
        self.assertEqual(self.client.get(reverse('monitor-api-orders')).status_code, 403)
        listings = self.client.get(reverse('monitor-api-listings'), {'q': 'Шат'}).json()
        self.assertEqual(listings['count'], 1)
        users = self.client.get(reverse('monitor-api-users')).json()
        self.assertGreaterEqual(users['count'], 2)
        self.assertEqual(self.client.get(reverse('monitor-api-deals')).status_code, 200)
        self.assertEqual(self.client.get(reverse('monitor-api-checks')).status_code, 200)
        funnel = self.client.get(reverse('monitor-api-funnel'), {'days': 7}).json()
        self.assertEqual(len(funnel['funnel']), 5)

    def test_live_without_redis_says_unavailable(self):
        self.login()
        with mock.patch('apps.monitoring.presence._redis', side_effect=RuntimeError('no redis')):
            self.assertEqual(self.client.get(reverse('monitor-api-live')).json(), {'available': False})


class PingTests(APITestCase):
    def test_ping_validates_and_records_first_visit(self):
        url = reverse('analytics-ping')
        self.assertEqual(self.client.post(url, {'visitor_id': 'x'}, format='json').status_code, 400)
        with mock.patch('apps.monitoring.presence.ping', return_value=True) as ping:
            response = self.client.post(url, {'visitor_id': 'abcdef123456', 'source': 'tma'}, format='json')
        self.assertEqual(response.status_code, 204)
        ping.assert_called_once_with('abcdef123456', 'tma', None)
        self.assertEqual(AuthEvent.objects.filter(event=AuthEvent.VISIT).count(), 1)

    def test_ping_with_token_counts_the_user(self):
        from rest_framework_simplejwt.tokens import RefreshToken

        user = make_user()
        token = RefreshToken.for_user(user).access_token
        with mock.patch('apps.monitoring.presence.ping', return_value=False) as ping:
            self.client.post(reverse('analytics-ping'), {'visitor_id': 'abcdef123456'}, format='json',
                             HTTP_X_AUTH_TOKEN=f'Bearer {token}')
            self.client.post(reverse('analytics-ping'), {'visitor_id': 'abcdef123456'}, format='json',
                             HTTP_X_AUTH_TOKEN='Bearer broken')
        self.assertEqual(ping.call_args_list[0].args, ('abcdef123456', 'web', user.pk))
        self.assertEqual(ping.call_args_list[1].args, ('abcdef123456', 'web', None))
        self.assertFalse(AuthEvent.objects.exists())

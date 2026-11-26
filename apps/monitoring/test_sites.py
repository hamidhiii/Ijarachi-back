"""«Обзор» раздельно по сайтам: rentoo.uz и owner.rentoo.uz."""
from unittest import mock

from django.test import RequestFactory
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.bookings.testing import make_user
from apps.monitoring import events, presence
from apps.monitoring.models import AuthEvent, MonitorAccess
from apps.monitoring.roles import ROLES


class FakePipe:
    """Запоминает команды пайплайна Redis — проверяем, какие ключи пишет ping."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args))
            return self
        return call

    def execute(self):
        return [True] * len(self.calls)


class FakeRedis:
    def __init__(self):
        self.pipe = FakePipe()

    def pipeline(self):
        return self.pipe

    def zcount(self, *args):
        return 0

    def get(self, key):
        return None

    def set(self, *args, **kwargs):
        return True

    def zremrangebyscore(self, *args):
        return 0


class SiteSplitTests(APITestCase):
    def test_ping_counts_the_site_separately(self):
        fake = FakeRedis()
        with mock.patch('apps.monitoring.presence._redis', return_value=fake):
            presence.ping('abcdef123456', 'owner', user_id=7)
        keys = {args[0] for name, args in fake.pipe.calls if name == 'pfadd'}
        day = presence._day()
        self.assertEqual(keys, {f'hll:v:{day}', f'hll:v:owner:{day}', f'hll:u:{day}', f'hll:u:owner:{day}'})

    def test_unknown_source_counts_as_web(self):
        fake = FakeRedis()
        with mock.patch('apps.monitoring.presence._redis', return_value=fake):
            presence.ping('abcdef123456', 'evil')
        keys = {args[0] for name, args in fake.pipe.calls if name == 'pfadd'}
        self.assertIn(f'hll:v:web:{presence._day()}', keys)

    def test_site_of_reads_origin_then_referer(self):
        factory = RequestFactory()
        self.assertEqual(events.site_of(factory.post('/', HTTP_ORIGIN='https://owner.rentoo.uz')), 'owner')
        self.assertEqual(events.site_of(factory.post('/', HTTP_ORIGIN='https://rentoo.uz')), 'web')
        self.assertEqual(events.site_of(factory.post('/', HTTP_REFERER='https://owner.rentoo.uz/login')), 'owner')
        self.assertEqual(events.site_of(factory.post('/')), 'web')

    def test_record_keeps_explicit_source(self):
        request = RequestFactory().post('/', HTTP_ORIGIN='https://rentoo.uz')
        events.record(request, AuthEvent.LOGIN_OK, phone='+998900000001', source='tma')
        events.record(request, AuthEvent.LOGIN_OK, phone='+998900000002')
        self.assertEqual(
            sorted(AuthEvent.objects.values_list('phone', 'source')),
            [('+998900000001', 'tma'), ('+998900000002', 'web')],
        )

    def test_ping_visit_event_gets_the_site(self):
        with mock.patch('apps.monitoring.presence.ping', return_value=True):
            self.client.post(reverse('analytics-ping'), {'visitor_id': 'abcdef123456', 'source': 'owner'},
                             format='json')
        self.assertEqual(AuthEvent.objects.get(event=AuthEvent.VISIT).source, 'owner')

    def test_overview_has_a_block_per_site(self):
        staff = make_user()
        MonitorAccess.objects.create(user=staff, permissions=ROLES['viewer'][1])
        request = RequestFactory().post('/', HTTP_ORIGIN='https://owner.rentoo.uz')
        # Один человек вошёл дважды и ещё один зарегистрировался — с owner; один — с rentoo.uz.
        events.record(request, AuthEvent.LOGIN_OK, phone='+998900000001')
        events.record(request, AuthEvent.LOGIN_OK, phone='+998900000001')
        events.record(request, AuthEvent.REGISTER_OK, phone='+998900000002')
        events.record(request, AuthEvent.OTP_SENT, phone='+998900000003')
        events.record(RequestFactory().post('/', HTTP_ORIGIN='https://rentoo.uz'), AuthEvent.LOGIN_OK,
                      phone='+998900000004')

        self.client.force_authenticate(staff)
        data = self.client.get(reverse('monitor-api-overview')).json()
        kpis = {k['key']: k for k in data['kpis']}
        self.assertEqual(kpis['logins_owner']['value'], 2)
        self.assertEqual(kpis['logins_web']['value'], 1)
        self.assertEqual(kpis['logins_owner']['group'], 'site_owner')
        self.assertEqual(sum(kpis['logins_owner']['series']), 2)
        for key in ('visitors_web', 'active_web', 'visitors_owner', 'active_owner'):
            self.assertIn(key, kpis)
            self.assertEqual(len(data['series'][key]), 7)

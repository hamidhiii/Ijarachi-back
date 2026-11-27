"""Оплата тарифа (заглушка, Payme, Click), окончание, напоминания, права."""
import base64
import hashlib
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.billing import tasks
from apps.billing.models import BillingOrder, Plan, Subscription, SubscriptionPeriod
from apps.billing.plans import current_plan
from apps.billing.services import extend_subscription
from apps.billing.testing import give_plan
from apps.bookings.testing import make_item, make_user
from apps.catalog.models import Item
from apps.notifications.models import Notification

PAYME_KEY = 'payme-test-key'
CLICK_KEY = 'click-test-key'


def payme_auth(key=PAYME_KEY):
    return 'Basic ' + base64.b64encode(f'Paycom:{key}'.encode()).decode()


class SubscriptionRulesTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.start = Plan.objects.get(code=Plan.START)
        self.pro = Plan.objects.get(code=Plan.PRO)

    def test_same_plan_extends_from_the_end(self):
        first = extend_subscription(self.user, self.start)
        end = first.ends_at
        second = extend_subscription(self.user, self.start)
        self.assertEqual(second.ends_at, end + timedelta(days=30))
        self.assertEqual(SubscriptionPeriod.objects.filter(user=self.user).count(), 2)

    def test_upgrade_starts_now_with_leftover_converted(self):
        extend_subscription(self.user, self.start)
        # Прошло 10 дней: осталось 20 дней START = 66 000 сум = 20 × 99 000 / 399 000 дней PRO.
        Subscription.objects.filter(user=self.user).update(ends_at=timezone.now() + timedelta(days=20))
        before = timezone.now()
        sub = extend_subscription(self.user, self.pro)
        self.assertEqual(sub.plan, self.pro)
        credit = timedelta(days=20) * 99000 / 399000
        self.assertAlmostEqual(sub.ends_at, before + timedelta(days=30) + credit, delta=timedelta(seconds=5))
        period = SubscriptionPeriod.objects.get(user=self.user, plan=self.pro)
        self.assertIn('+5.0 дн. за остаток START', period.comment)
        # Период START в истории обрезан моментом перехода.
        start_period = SubscriptionPeriod.objects.get(user=self.user, plan=self.start)
        self.assertLessEqual(start_period.ends_at, timezone.now())

    def test_renewing_the_same_plan_has_no_credit(self):
        first = extend_subscription(self.user, self.pro).ends_at
        self.assertEqual(extend_subscription(self.user, self.pro).ends_at, first + timedelta(days=30))

    def test_upgrade_after_expiry_has_no_credit(self):
        extend_subscription(self.user, self.start)
        Subscription.objects.filter(user=self.user).update(ends_at=timezone.now() - timedelta(days=1))
        before = timezone.now()
        sub = extend_subscription(self.user, self.pro)
        self.assertAlmostEqual(sub.ends_at, before + timedelta(days=30), delta=timedelta(seconds=5))

    def test_downgrade_refused_while_active(self):
        extend_subscription(self.user, self.pro)
        self.client.force_authenticate(self.user)
        response = self.client.post(reverse('billing-orders'), {'plan': 'start', 'provider': 'click'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'PLAN_DOWNGRADE_WHILE_ACTIVE')

    def test_free_is_not_for_sale(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(reverse('billing-orders'), {'plan': 'free', 'provider': 'click'}, format='json')
        self.assertEqual(response.json()['code'], 'PLAN_NOT_FOR_SALE')


class StubCheckoutTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.client.force_authenticate(self.user)

    def test_plans_are_public(self):
        self.client.force_authenticate(None)
        codes = [p['code'] for p in self.client.get(reverse('billing-plans')).json()]
        self.assertEqual(codes, ['free', 'start', 'business', 'pro'])

    def test_stub_pays_at_once(self):
        response = self.client.post(reverse('billing-orders'), {'plan': 'business', 'provider': 'payme'}, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body['status'], body['provider'], body['amount']), ('paid', 'stub', '199000'))
        self.assertIn(f'/billing/orders/{body["id"]}', body['redirect_url'])
        self.assertEqual(current_plan(self.user).code, Plan.BUSINESS)

        state = self.client.get(reverse('billing-subscription')).json()
        self.assertEqual((state['plan']['code'], state['listing_limit'], state['days_left']), ('business', 300, 30))
        self.assertEqual(self.client.get(reverse('billing-order-detail', kwargs={'pk': body['id']})).json()['status'], 'paid')

    @override_settings(PAYMENTS_MODE='off')
    def test_off_mode_is_503(self):
        response = self.client.post(reverse('billing-orders'), {'plan': 'start', 'provider': 'click'}, format='json')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(BillingOrder.objects.exists())

    @override_settings(PAYMENTS_MODE='live', CLICK_SERVICE_ID='11', CLICK_MERCHANT_ID='22', PAYME_MERCHANT_ID='m1')
    def test_live_mode_gives_checkout_links(self):
        click = self.client.post(reverse('billing-orders'), {'plan': 'start', 'provider': 'click'}, format='json').json()
        self.assertTrue(click['redirect_url'].startswith('https://my.click.uz/services/pay?'))
        self.assertIn(f'transaction_param={click["id"]}', click['redirect_url'])
        self.assertIn('amount=99000', click['redirect_url'])
        payme = self.client.post(reverse('billing-orders'), {'plan': 'start', 'provider': 'payme'}, format='json').json()
        decoded = base64.b64decode(payme['redirect_url'].rsplit('/', 1)[1]).decode()
        self.assertIn(f'ac.order_id={payme["id"]};a=9900000;', decoded)
        self.assertEqual(current_plan(self.user).code, Plan.FREE)

    def test_webhooks_404_unless_live(self):
        for name in ('billing-payme', 'billing-click-prepare', 'billing-click-complete'):
            self.assertEqual(self.client.post(reverse(name), {}).status_code, 404)


@override_settings(PAYMENTS_MODE='live', PAYME_SECRET_KEY=PAYME_KEY)
class PaymeTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.order = BillingOrder.objects.create(
            user=self.user, kind=BillingOrder.KIND_PLAN, plan=Plan.objects.get(code=Plan.START),
            amount=99000, provider=BillingOrder.PROVIDER_PAYME,
        )

    def rpc(self, method, params, auth=None):
        response = self.client.post(
            reverse('billing-payme'), {'jsonrpc': '2.0', 'id': 7, 'method': method, 'params': params},
            format='json', HTTP_AUTHORIZATION=auth or payme_auth(),
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def account(self, **extra):
        return {'amount': 9900000, 'account': {'order_id': self.order.pk}, **extra}

    def test_wrong_key_is_rejected(self):
        body = self.rpc('CheckPerformTransaction', self.account(), auth=payme_auth('wrong'))
        self.assertEqual(body['error']['code'], -32504)

    def test_full_payment(self):
        self.assertIs(self.rpc('CheckPerformTransaction', self.account())['result']['allow'], True)
        created = self.rpc('CreateTransaction', self.account(id='tx1', time=1))['result']
        self.assertEqual(created['state'], 1)
        # Повтор Create с тем же id — тот же ответ.
        self.assertEqual(self.rpc('CreateTransaction', self.account(id='tx1', time=1))['result'], created)
        performed = self.rpc('PerformTransaction', {'id': 'tx1'})['result']
        self.assertEqual(performed['state'], 2)
        self.assertEqual(self.rpc('PerformTransaction', {'id': 'tx1'})['result'], performed)
        self.assertEqual(current_plan(self.user).code, Plan.START)
        self.assertEqual(SubscriptionPeriod.objects.filter(user=self.user).count(), 1)
        check = self.rpc('CheckTransaction', {'id': 'tx1'})['result']
        self.assertEqual((check['state'], check['transaction']), (2, str(self.order.pk)))
        # Услуга оказана — отменить нельзя.
        self.assertEqual(self.rpc('CancelTransaction', {'id': 'tx1', 'reason': 5})['error']['code'], -31007)
        statement = self.rpc('GetStatement', {'from': 0, 'to': 10 ** 14})['result']['transactions']
        self.assertEqual([t['id'] for t in statement], ['tx1'])

    def test_wrong_amount_and_unknown_order(self):
        self.assertEqual(self.rpc('CheckPerformTransaction', self.account(amount=100))['error']['code'], -31001)
        body = self.rpc('CheckPerformTransaction', {'amount': 9900000, 'account': {'order_id': 999999}})
        self.assertEqual(body['error']['code'], -31050)

    def test_second_transaction_for_the_same_order_is_refused(self):
        self.rpc('CreateTransaction', self.account(id='tx1', time=1))
        self.assertEqual(self.rpc('CreateTransaction', self.account(id='tx2', time=2))['error']['code'], -31052)

    def test_cancel_before_perform(self):
        self.rpc('CreateTransaction', self.account(id='tx1', time=1))
        cancelled = self.rpc('CancelTransaction', {'id': 'tx1', 'reason': 3})['result']
        self.assertEqual(cancelled['state'], -1)
        self.assertEqual(self.rpc('PerformTransaction', {'id': 'tx1'})['error']['code'], -31008)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, BillingOrder.STATUS_CANCELLED)
        self.assertEqual(current_plan(self.user).code, Plan.FREE)

    def test_timed_out_transaction_is_cancelled(self):
        self.rpc('CreateTransaction', self.account(id='tx1', time=1))
        BillingOrder.objects.filter(pk=self.order.pk).update(provider_create_time=1)
        self.assertEqual(self.rpc('PerformTransaction', {'id': 'tx1'})['error']['code'], -31008)
        self.order.refresh_from_db()
        self.assertEqual((self.order.provider_state, self.order.cancel_reason), (-1, 4))

    def test_unknown_method_and_transaction(self):
        self.assertEqual(self.rpc('Nope', {})['error']['code'], -32601)
        self.assertEqual(self.rpc('CheckTransaction', {'id': 'missing'})['error']['code'], -31003)


@override_settings(PAYMENTS_MODE='live', CLICK_SECRET_KEY=CLICK_KEY)
class ClickTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.order = BillingOrder.objects.create(
            user=self.user, kind=BillingOrder.KIND_PLAN, plan=Plan.objects.get(code=Plan.PRO),
            amount=399000, provider=BillingOrder.PROVIDER_CLICK,
        )

    def call(self, action, **overrides):
        data = {
            'click_trans_id': '555', 'service_id': '11', 'click_paydoc_id': '9',
            'merchant_trans_id': str(self.order.pk), 'amount': '399000.00', 'action': str(action),
            'error': '0', 'error_note': 'ok', 'sign_time': '2026-11-16 10:00:00',
        }
        if action == 1:
            data['merchant_prepare_id'] = str(self.order.pk)
        data.update(overrides)
        prepare_id = data.get('merchant_prepare_id', '') if action == 1 else ''
        raw = (f"{data['click_trans_id']}{data['service_id']}{CLICK_KEY}{data['merchant_trans_id']}"
               f"{prepare_id}{data['amount']}{data['action']}{data['sign_time']}")
        data.setdefault('sign_string', hashlib.md5(raw.encode()).hexdigest())
        url = reverse('billing-click-prepare' if action == 0 else 'billing-click-complete')
        return self.client.post(url, data).json()

    def test_prepare_and_complete(self):
        prepared = self.call(0)
        self.assertEqual((prepared['error'], prepared['merchant_prepare_id']), (0, self.order.pk))
        completed = self.call(1)
        self.assertEqual((completed['error'], completed['merchant_confirm_id']), (0, self.order.pk))
        self.assertEqual(current_plan(self.user).code, Plan.PRO)
        # Повторный Complete — «уже оплачен», второй период не появляется.
        self.assertEqual(self.call(1)['error'], -4)
        self.assertEqual(SubscriptionPeriod.objects.filter(user=self.user).count(), 1)

    def test_bad_sign(self):
        self.assertEqual(self.call(0, sign_string='0' * 32)['error'], -1)

    def test_wrong_amount(self):
        self.assertEqual(self.call(0, amount='1000.00')['error'], -2)

    def test_unknown_order(self):
        self.assertEqual(self.call(0, merchant_trans_id='999999')['error'], -5)

    def test_click_side_failure_cancels(self):
        self.call(0)
        self.assertEqual(self.call(1, error='-5017')['error'], -9)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, BillingOrder.STATUS_CANCELLED)
        self.assertEqual(current_plan(self.user).code, Plan.FREE)

    def test_complete_without_prepare(self):
        self.assertEqual(self.call(1)['error'], -6)


class ExpiryTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        Plan.objects.filter(code=Plan.FREE).update(listing_limit=2)

    def expire(self):
        Subscription.objects.filter(user=self.user).update(ends_at=timezone.now() - timedelta(minutes=1))
        with mock.patch('apps.notifications.tasks.send_telegram_notification.delay'), \
                mock.patch('apps.notifications.tasks.send_web_push.delay'), \
                self.captureOnCommitCallbacks(execute=True):
            return tasks.expire_subscriptions()

    def test_extra_listings_are_paused_not_deleted(self):
        give_plan(self.user, Plan.START)
        old = make_item(self.user)
        vip = make_item(self.user, vip_until=timezone.now() + timedelta(days=3))
        newest = make_item(self.user, status=Item.STATUS_PENDING)
        withdrawn = make_item(self.user, status=Item.STATUS_INACTIVE)
        Item.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=5))

        self.assertEqual(self.expire(), 1)

        statuses = dict(Item.objects.filter(owner=self.user).values_list('pk', 'status'))
        self.assertEqual(statuses[vip.pk], Item.STATUS_APPROVED)
        self.assertEqual(statuses[newest.pk], Item.STATUS_PENDING)
        self.assertEqual(statuses[old.pk], Item.STATUS_INACTIVE)
        self.assertEqual(statuses[withdrawn.pk], Item.STATUS_INACTIVE)
        self.assertEqual(Item.objects.get(pk=old.pk).plan_paused_status, Item.STATUS_APPROVED)
        self.assertEqual(Item.objects.get(pk=withdrawn.pk).plan_paused_status, '')
        self.assertEqual(Item.objects.filter(owner=self.user).count(), 4)
        note = Notification.objects.get(user=self.user, type=Notification.TYPE_BILLING)
        self.assertIn('1 объявл.', note.payload['message'])
        # Повторный запуск ничего не делает.
        self.assertEqual(tasks.expire_subscriptions(), 0)

    def test_paying_again_restores_paused_listings(self):
        give_plan(self.user, Plan.START)
        items = [make_item(self.user) for _ in range(3)]
        withdrawn = make_item(self.user, status=Item.STATUS_INACTIVE)
        self.expire()
        self.assertEqual(Item.objects.filter(owner=self.user, status=Item.STATUS_APPROVED).count(), 2)

        self.client.force_authenticate(self.user)
        self.client.post(reverse('billing-orders'), {'plan': 'start', 'provider': 'click'}, format='json')

        self.assertEqual(
            set(Item.objects.filter(owner=self.user, status=Item.STATUS_APPROVED).values_list('pk', flat=True)),
            {item.pk for item in items},
        )
        withdrawn.refresh_from_db()
        self.assertEqual(withdrawn.status, Item.STATUS_INACTIVE)

    def test_owner_touched_paused_listing_is_not_restored(self):
        give_plan(self.user, Plan.START)
        items = [make_item(self.user) for _ in range(3)]
        Item.objects.filter(pk=items[0].pk).update(created_at=timezone.now() - timedelta(days=1))
        self.expire()
        paused = Item.objects.get(pk=items[0].pk)
        self.assertEqual(paused.status, Item.STATUS_INACTIVE)
        self.client.force_authenticate(self.user)
        self.client.patch(reverse('listing-detail', kwargs={'pk': paused.pk}), {'status': 'inactive'}, format='json')
        self.client.post(reverse('billing-orders'), {'plan': 'start', 'provider': 'click'}, format='json')
        paused.refresh_from_db()
        self.assertEqual((paused.status, paused.plan_paused_status), (Item.STATUS_INACTIVE, ''))


class ReminderTests(APITestCase):
    def setUp(self):
        self.user = make_user()

    def remind(self):
        with mock.patch('apps.notifications.tasks.send_telegram_notification.delay'), \
                mock.patch('apps.notifications.tasks.send_web_push.delay'), \
                self.captureOnCommitCallbacks(execute=True):
            return tasks.remind_subscriptions()

    def set_end(self, days):
        give_plan(self.user, Plan.START)
        end = timezone.localtime() + timedelta(days=days)
        end = end.replace(hour=23, minute=0) if days else end.replace(hour=23, minute=59)
        Subscription.objects.filter(user=self.user).update(ends_at=end)

    def test_three_days_before(self):
        self.set_end(3)
        self.assertEqual(self.remind(), 1)
        self.assertEqual(self.remind(), 0)
        note = Notification.objects.get(user=self.user)
        self.assertEqual(note.payload['title'], 'Тариф заканчивается через 3 дня')
        self.assertTrue(note.payload['link'].endswith('/billing'))

    def test_last_day(self):
        self.set_end(0)
        self.assertEqual(self.remind(), 1)
        self.assertEqual(Notification.objects.get(user=self.user).payload['title'], 'Тариф заканчивается сегодня')

    def test_no_reminder_in_between(self):
        self.set_end(5)
        self.assertEqual(self.remind(), 0)


class FeatureRightsTests(APITestCase):
    def test_rights_by_plan(self):
        from apps.billing.plans import has_feature, require_feature

        user = make_user()
        self.assertFalse(has_feature(user, 'statistics'))
        give_plan(user, Plan.BUSINESS)
        self.assertTrue(has_feature(user, 'staff_access'))
        self.assertFalse(has_feature(user, 'data_export'))
        with self.assertRaises(Exception) as ctx:
            require_feature(user, 'branches')
        self.assertEqual(ctx.exception.detail['required_plan'], 'pro')
        give_plan(user, Plan.PRO)
        self.assertTrue(has_feature(user, 'branches'))

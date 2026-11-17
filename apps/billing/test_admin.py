"""Админ-API тарифов: списки, ручное продление, метрики (MRR, отток, выручка)."""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.billing.models import BillingOrder, Plan, Subscription, SubscriptionPeriod
from apps.billing.testing import give_plan
from apps.bookings.testing import make_item, make_user
from apps.catalog.models import Item


class BillingAdminTests(APITestCase):
    def setUp(self):
        self.staff = make_user()
        self.staff.is_staff = True
        self.staff.save()
        self.client.force_authenticate(self.staff)

    def test_staff_only(self):
        self.client.force_authenticate(make_user())
        for name in ('admin-billing-subscriptions', 'admin-billing-orders', 'admin-billing-metrics'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_manual_extension_by_phone(self):
        user = make_user()
        response = self.client.post(reverse('admin-billing-extend'), {
            'phone': user.phone, 'plan': 'business', 'days': 60, 'comment': 'Оплатил наличными',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()['plan'], response.json()['is_active']), ('business', True))
        period = SubscriptionPeriod.objects.get(user=user)
        self.assertEqual((period.source, period.created_by, period.comment), ('manual', self.staff, 'Оплатил наличными'))
        self.assertAlmostEqual(period.ends_at - period.starts_at, timedelta(days=60), delta=timedelta(seconds=1))

    def test_manual_downgrade_is_allowed_and_restores_paused(self):
        user = make_user()
        give_plan(user, Plan.PRO)
        paused = make_item(user, status=Item.STATUS_INACTIVE, plan_paused_status=Item.STATUS_APPROVED)
        self.client.post(reverse('admin-billing-extend'), {'user': user.pk, 'plan': 'start'}, format='json')
        self.assertEqual(Subscription.objects.get(user=user).plan.code, Plan.START)
        paused.refresh_from_db()
        self.assertEqual(paused.status, Item.STATUS_APPROVED)

    def test_lists(self):
        user = make_user()
        give_plan(user, Plan.START)
        BillingOrder.objects.create(user=user, kind='plan', plan=Plan.objects.get(code='start'), amount=99000,
                                    provider='click', status='paid', paid_at=timezone.now())
        BillingOrder.objects.create(user=user, kind='plan', plan=Plan.objects.get(code='pro'), amount=399000,
                                    provider='payme', status='paid', needs_attention='Не применён')
        subs = self.client.get(reverse('admin-billing-subscriptions'), {'state': 'active'}).json()['results']
        self.assertEqual((subs[0]['phone'], subs[0]['plan'], subs[0]['paid_total']), (user.phone, 'start', '498000'))
        attention = self.client.get(reverse('admin-billing-orders'), {'needs_attention': 1}).json()['results']
        self.assertEqual([o['plan'] for o in attention], ['pro'])

    def test_metrics(self):
        now = timezone.now()
        start, business, pro = (Plan.objects.get(code=c) for c in ('start', 'business', 'pro'))
        a, b, c, gone = make_user(), make_user(), make_user(), make_user()
        give_plan(a, Plan.START)
        give_plan(b, Plan.BUSINESS)
        give_plan(c, Plan.BUSINESS)
        # Платил 40 дней назад, не продлил — отток.
        SubscriptionPeriod.objects.create(user=gone, plan=pro, starts_at=now - timedelta(days=40),
                                          ends_at=now - timedelta(days=10), source='payment')
        Subscription.objects.create(user=gone, plan=pro, ends_at=now - timedelta(days=10))
        # a платил и до начала периода — остался.
        SubscriptionPeriod.objects.create(user=a, plan=start, starts_at=now - timedelta(days=45),
                                          ends_at=now - timedelta(days=1), source='payment')
        BillingOrder.objects.create(user=b, kind='plan', plan=business, amount=199000, provider='click',
                                    status='paid', paid_at=now)
        BillingOrder.objects.create(user=b, kind='promotion', promotion='vip', amount=80000, provider='payme',
                                    status='paid', paid_at=now)
        BillingOrder.objects.create(user=c, kind='plan', plan=business, amount=199000, provider='stub',
                                    status='paid', paid_at=now)

        data = self.client.get(reverse('admin-billing-metrics')).json()
        self.assertEqual(data['paying_by_plan'], {'start': 1, 'business': 2, 'pro': 0})
        self.assertEqual(data['paying_total'], 3)
        self.assertEqual(data['mrr'], 99000 + 2 * 199000)
        self.assertEqual(data['churn'], {'days': 30, 'paying_at_start': 2, 'churned': 1, 'rate': 0.5})
        self.assertEqual(data['revenue'], {'days': 30, 'total': 279000, 'plans': 199000, 'promotions': 80000})
        self.assertEqual(data['new_paying'], 2)

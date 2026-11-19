"""Django-админка: выдать, сменить и завершить тариф, заказы, продвижение — всё через сервисы и с историей."""
from datetime import timedelta

from django.contrib.admin import helpers
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import BillingOrder, Plan, Promotion, Subscription, SubscriptionPeriod
from apps.billing.testing import give_plan
from apps.bookings.testing import make_item, make_user
from apps.catalog.models import Item


class DjangoAdminBillingTests(TestCase):
    def setUp(self):
        self.staff = make_user(is_staff=True, is_superuser=True)
        self.client.force_login(self.staff)
        self.user = make_user()

    def plan(self, code):
        return Plan.objects.get(code=code)

    def action(self, url, name, objects, **form):
        data = {'action': name, helpers.ACTION_CHECKBOX_NAME: [o.pk for o in objects], 'index': 0}
        if form:
            data.update(apply='1', **form)
        return self.client.post(url, data)

    def test_pages_open(self):
        give_plan(self.user, Plan.START)
        item = make_item(self.user)
        sub = Subscription.objects.get(user=self.user)
        order = BillingOrder.objects.create(user=self.user, kind='plan', plan=self.plan('start'), amount=99000,
                                            provider='click')
        for url in (
            reverse('admin:users_customuser_changelist'),
            reverse('admin:users_customuser_changelist') + '?plan=start',
            reverse('admin:users_customuser_change', args=[self.user.pk]),
            reverse('admin:billing_plan_changelist'),
            reverse('admin:billing_subscription_changelist') + '?state=week',
            reverse('admin:billing_subscription_add') + f'?user={self.user.pk}',
            reverse('admin:billing_subscription_change', args=[sub.pk]),
            reverse('admin:billing_billingorder_changelist') + '?attention=yes',
            reverse('admin:billing_billingorder_change', args=[order.pk]),
            reverse('admin:billing_promotion_add'),
            reverse('admin:catalog_item_changelist'),
            reverse('admin:catalog_item_change', args=[item.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_add_subscription_grants_plan_with_history(self):
        response = self.client.post(reverse('admin:billing_subscription_add'), {
            'user': self.user.pk, 'new_plan': self.plan('business').pk, 'days': 45, 'amount': 150000,
            'comment': 'наличные', 'notify': 'on',
        })
        self.assertEqual(response.status_code, 302, getattr(response, 'context_data', {}).get('errors'))
        sub = Subscription.objects.get(user=self.user)
        self.assertEqual(sub.plan.code, 'business')
        period = SubscriptionPeriod.objects.get(user=self.user)
        self.assertEqual((period.source, period.created_by, period.amount, period.comment),
                         ('manual', self.staff, 150000, 'наличные'))
        self.assertAlmostEqual(period.ends_at - period.starts_at, timedelta(days=45), delta=timedelta(seconds=5))

    def test_change_form_switches_plan_and_empty_changes_nothing(self):
        give_plan(self.user, Plan.PRO)
        sub = Subscription.objects.get(user=self.user)
        url = reverse('admin:billing_subscription_change', args=[sub.pk])
        self.client.post(url, {'new_plan': '', 'days': '', 'amount': '', 'comment': ''})
        self.assertEqual(SubscriptionPeriod.objects.filter(user=self.user).count(), 1)

        self.client.post(url, {'new_plan': self.plan('start').pk, 'days': 30, 'amount': 0, 'comment': ''})
        sub.refresh_from_db()
        self.assertEqual(sub.plan.code, 'start')  # понижение сотрудником — сразу

    def test_free_finishes_now_and_pauses_extra_listings(self):
        give_plan(self.user, Plan.BUSINESS)
        free_limit = self.plan('free').listing_limit
        for _ in range(free_limit + 2):
            make_item(self.user)
        sub = Subscription.objects.get(user=self.user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('admin:billing_subscription_change', args=[sub.pk]),
                             {'new_plan': self.plan('free').pk, 'comment': 'просил'})
        sub.refresh_from_db()
        self.assertLessEqual(sub.ends_at, timezone.now())
        self.assertEqual(Item.objects.filter(owner=self.user, status=Item.STATUS_APPROVED).count(), free_limit)
        period = SubscriptionPeriod.objects.get(user=self.user)
        self.assertIn('Завершён досрочно', period.comment)
        self.assertLessEqual(period.ends_at, timezone.now())

    def test_user_list_action_shows_form_then_applies(self):
        other = make_user()
        url = reverse('admin:users_customuser_changelist')
        page = self.action(url, 'grant_plan', [self.user, other])
        self.assertContains(page, 'Применить')
        self.action(url, 'grant_plan', [self.user, other], plan=self.plan('start').pk, days=30, amount=0)
        self.assertEqual(Subscription.objects.filter(plan__code='start', ends_at__gt=timezone.now()).count(), 2)

        with self.captureOnCommitCallbacks(execute=True):
            self.action(url, 'finish_plan', [self.user])
        self.assertFalse(Subscription.objects.filter(user=self.user, ends_at__gt=timezone.now()).exists())

    def test_order_mark_paid_applies_plan(self):
        order = BillingOrder.objects.create(user=self.user, kind='plan', plan=self.plan('start'), amount=99000,
                                            provider='click')
        with self.captureOnCommitCallbacks(execute=True):
            self.action(reverse('admin:billing_billingorder_changelist'), 'mark_paid', [order])
        order.refresh_from_db()
        self.assertEqual(order.status, 'paid')
        self.assertEqual(order.raw['manual_paid_by'], str(self.staff))
        self.assertEqual(Subscription.objects.get(user=self.user).plan.code, 'start')

    def test_promotion_grant_and_stop(self):
        item = make_item(self.user)
        self.client.post(reverse('admin:billing_promotion_add'),
                         {'item': item.pk, 'kind': 'vip', 'days': 5, 'notify': 'on'})
        item.refresh_from_db()
        self.assertGreater(item.vip_until, timezone.now() + timedelta(days=4))
        self.assertIsNone(Promotion.objects.get(item=item).order)

        url = reverse('admin:catalog_item_changelist')
        self.action(url, 'grant_promotion', [item], kind='top', days=3)
        self.action(url, 'stop_promotion', [item], kind='all')
        item.refresh_from_db()
        self.assertLessEqual(item.vip_until, timezone.now())
        self.assertLessEqual(item.top_until, timezone.now())

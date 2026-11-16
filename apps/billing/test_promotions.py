"""Продвижение объявления и порядок выдачи: VIP > топ > приоритет тарифа > дата."""
from datetime import timedelta

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.billing.models import BillingOrder, Plan, Promotion
from apps.billing.testing import give_plan
from apps.bookings.testing import make_item, make_user
from apps.catalog.models import Item


class PromotionPurchaseTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.item = make_item(self.owner)
        self.client.force_authenticate(self.owner)

    def buy(self, kind, listing=None):
        return self.client.post(reverse('billing-orders'), {
            'kind': 'promotion', 'promotion': kind, 'listing': listing or self.item.pk, 'provider': 'click',
        }, format='json')

    def test_offers_are_public(self):
        self.client.force_authenticate(None)
        offers = {o['kind']: (o['price'], o['days']) for o in self.client.get(reverse('billing-promotions')).json()}
        self.assertEqual(offers, {'top': (30000, 7), 'vip': (80000, 30)})

    def test_top_for_seven_days(self):
        response = self.buy('top')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual((response.json()['amount'], response.json()['status']), ('30000', 'paid'))
        self.item.refresh_from_db()
        self.assertAlmostEqual(self.item.top_until, timezone.now() + timedelta(days=7), delta=timedelta(seconds=5))
        self.assertIsNone(self.item.vip_until)
        self.assertEqual(Promotion.objects.get(item=self.item).kind, 'top')
        card = self.client.get(reverse('listing-detail', kwargs={'pk': self.item.pk})).json()
        self.assertEqual((card['is_top'], card['is_vip']), (True, False))

    def test_vip_thirty_days_and_repeat_extends(self):
        self.buy('vip')
        first_end = Item.objects.get(pk=self.item.pk).vip_until
        self.buy('vip')
        self.assertEqual(Item.objects.get(pk=self.item.pk).vip_until, first_end + timedelta(days=30))
        self.assertAlmostEqual(first_end, timezone.now() + timedelta(days=30), delta=timedelta(seconds=5))

    def test_someone_elses_or_unpublished_listing(self):
        stranger = make_item(make_user())
        self.assertEqual(self.buy('top', listing=stranger.pk).json()['code'], 'LISTING_NOT_FOUND')
        pending = make_item(self.owner, status=Item.STATUS_PENDING)
        self.assertEqual(self.buy('top', listing=pending.pk).json()['code'], 'LISTING_NOT_PUBLISHED')
        self.assertFalse(BillingOrder.objects.exists())

    @override_settings(PAYMENTS_MODE='live')
    def test_listing_withdrawn_before_payment_is_not_payable(self):
        from apps.billing.services import OrderNotPayable, check_order_payable

        order_id = self.buy('vip').json()['id']
        Item.objects.filter(pk=self.item.pk).update(status=Item.STATUS_INACTIVE)
        with self.assertRaises(OrderNotPayable):
            check_order_payable(BillingOrder.objects.get(pk=order_id))


class SearchOrderingTests(APITestCase):
    def setUp(self):
        cache.clear()
        now = timezone.now()
        self.plain_new = make_item(make_user())
        business_owner = make_user()
        give_plan(business_owner, Plan.BUSINESS)
        self.business_old = make_item(business_owner)
        self.top = make_item(make_user(), top_until=now + timedelta(days=1))
        self.vip_old = make_item(make_user(), vip_until=now + timedelta(days=1))
        self.expired_vip = make_item(make_user(), vip_until=now - timedelta(minutes=1))
        Item.objects.filter(pk__in=[self.business_old.pk, self.vip_old.pk]).update(
            created_at=now - timedelta(days=10),
        )
        Item.objects.filter(pk=self.plain_new.pk).update(created_at=now + timedelta(seconds=1))

    def ids(self, **params):
        return [row['id'] for row in self.client.get(reverse('listing-list-create'), params).json()['results']]

    def test_default_order(self):
        self.assertEqual(self.ids(), [
            self.vip_old.pk, self.top.pk, self.business_old.pk, self.plain_new.pk, self.expired_vip.pk,
        ])

    def test_explicit_price_order_is_kept(self):
        Item.objects.filter(pk=self.plain_new.pk).update(price_per_day=1)
        self.assertEqual(self.ids(ordering='price')[0], self.plain_new.pk)

    def test_expired_business_plan_loses_priority(self):
        from apps.billing.models import Subscription

        Subscription.objects.update(ends_at=timezone.now() - timedelta(minutes=1))
        ids = self.ids()
        self.assertLess(ids.index(self.plain_new.pk), ids.index(self.business_old.pk))

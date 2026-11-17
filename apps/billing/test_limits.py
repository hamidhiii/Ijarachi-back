"""Лимит активных объявлений по тарифу и количество у объявления."""
from datetime import timedelta

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.billing.models import Plan, Subscription
from apps.billing.testing import give_plan, listing_payload
from apps.bookings.testing import make_item, make_user
from apps.catalog.models import Category, Item


class PlanLimitTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.category, _ = Category.objects.get_or_create(slug='test-limit', defaults={'name': 'Test'})
        # Лимиты меньше настоящих, чтобы не создавать по 100 объявлений.
        Plan.objects.filter(code=Plan.FREE).update(listing_limit=2)
        Plan.objects.filter(code=Plan.START).update(listing_limit=3)

    def create(self, url_name='listing-list-create'):
        return self.client.post(reverse(url_name), listing_payload(self.category), format='json')

    def assertLimitReached(self, response, plan='free', limit=2):
        self.assertEqual(response.status_code, 400, response.content)
        body = response.json()
        self.assertEqual(body['code'], 'LIMIT_REACHED')
        self.assertEqual((body['plan'], body['limit']), (plan, limit))
        self.assertIn('detail', body)

    def test_seeded_plans(self):
        plans = {p.code: (p.price, p.listing_limit) for p in Plan.objects.all()}
        self.assertEqual(plans['start'], (99000, 3))  # лимит переопределён в setUp
        self.assertEqual(plans['business'], (199000, 300))
        self.assertEqual(plans['pro'], (399000, None))

    def test_free_stops_at_limit(self):
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create().status_code, 201)
        self.assertLimitReached(self.create())
        self.assertEqual(Item.objects.filter(owner=self.user).count(), 2)

    def test_legacy_create_endpoint_also_limited(self):
        make_item(self.user)
        make_item(self.user)
        self.assertLimitReached(self.create('item-create'))

    def test_inactive_and_rejected_do_not_count(self):
        for status in (Item.STATUS_INACTIVE, Item.STATUS_REJECTED, Item.STATUS_INACTIVE):
            make_item(self.user, status=status)
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create().status_code, 201)

    def test_paid_plan_raises_the_limit(self):
        give_plan(self.user, Plan.START)
        for _ in range(3):
            self.assertEqual(self.create().status_code, 201)
        self.assertLimitReached(self.create(), plan='start', limit=3)

    def test_pro_has_no_limit(self):
        give_plan(self.user, Plan.PRO)
        for _ in range(5):
            self.assertEqual(self.create().status_code, 201)
        data = self.client.get(reverse('user-profile')).json()
        self.assertEqual((data['listing_limit'], data['live_listings']), (None, 5))

    def test_expired_plan_falls_back_to_free(self):
        give_plan(self.user, Plan.START)
        Subscription.objects.filter(user=self.user).update(ends_at=timezone.now() - timedelta(minutes=1))
        make_item(self.user)
        make_item(self.user)
        self.assertLimitReached(self.create())

    def test_activating_a_withdrawn_listing_counts(self):
        make_item(self.user)
        make_item(self.user)
        withdrawn = make_item(self.user, status=Item.STATUS_INACTIVE)
        response = self.client.patch(reverse('listing-detail', kwargs={'pk': withdrawn.pk}), {'status': 'pending'}, format='json')
        self.assertLimitReached(response)
        withdrawn.refresh_from_db()
        self.assertEqual(withdrawn.status, Item.STATUS_INACTIVE)

    def test_editing_a_live_listing_is_not_blocked(self):
        first = make_item(self.user)
        make_item(self.user)
        response = self.client.patch(reverse('listing-detail', kwargs={'pk': first.pk}), {'price_per_day': '70000'}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_shop_account_type_no_longer_raises_the_limit(self):
        self.client.patch(reverse('user-profile'), {'account_type': 'shop', 'shop_name': 'Прокат'}, format='json')
        self.create()
        self.create()
        self.assertLimitReached(self.create())


class QuantityTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.category, _ = Category.objects.get_or_create(slug='test-qty', defaults={'name': 'Test'})

    def test_defaults_to_one(self):
        response = self.client.post(reverse('listing-list-create'), listing_payload(self.category), format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Item.objects.get(owner=self.user).quantity, 1)

    def test_set_on_create_and_shown_in_catalog(self):
        response = self.client.post(
            reverse('listing-list-create'), listing_payload(self.category, quantity=40), format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        item = Item.objects.get(owner=self.user)
        self.assertEqual(item.quantity, 40)
        Item.objects.filter(pk=item.pk).update(status=Item.STATUS_APPROVED)
        self.assertEqual(self.client.get(reverse('listing-detail', kwargs={'pk': item.pk})).json()['quantity'], 40)
        rows = self.client.get(reverse('listing-list-create')).json()['results']
        self.assertEqual(rows[0]['quantity'], 40)

    def test_must_be_at_least_one(self):
        for bad in (0, -3):
            with self.subTest(quantity=bad):
                response = self.client.post(
                    reverse('listing-list-create'), listing_payload(self.category, quantity=bad), format='json',
                )
                self.assertEqual(response.status_code, 400)
        item = make_item(self.user)
        response = self.client.patch(reverse('listing-detail', kwargs={'pk': item.pk}), {'quantity': 0}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_owner_changes_quantity_without_remoderation(self):
        item = make_item(self.user, status=Item.STATUS_APPROVED)
        response = self.client.patch(reverse('listing-detail', kwargs={'pk': item.pk}), {'quantity': 12}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        item.refresh_from_db()
        self.assertEqual((item.quantity, item.status), (12, Item.STATUS_APPROVED))

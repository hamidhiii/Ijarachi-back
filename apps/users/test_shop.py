"""Тип аккаунта: частное лицо ↔ магазин и то, что магазин получает сверх частника."""
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.bookings.models import Booking
from apps.bookings.testing import make_booking, make_item, make_user
from apps.catalog.models import Category, Item
from apps.users.models import Profile


def set_profile(user, **fields):
    # Профиль создаётся сигналом вместе с пользователем.
    Profile.objects.filter(user=user).update(**fields)
    return Profile.objects.get(user=user)


def listing_payload(category):
    return {
        'title': 'Платье', 'description': 'Вечернее', 'category': category.pk,
        'price_per_day': '50000', 'deposit': '0', 'condition': 'good',
        'address': 'Ташкент', 'city': 'Ташкент',
    }


class AccountSwitchTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.url = reverse('user-profile')

    def test_new_account_is_private(self):
        data = self.client.get(self.url).json()
        self.assertEqual(data['account_type'], 'private')
        self.assertEqual(data['listing_limit'], 10)
        self.assertEqual(data['live_listings'], 0)

    def test_switch_to_shop_requires_name(self):
        response = self.client.patch(self.url, {'account_type': 'shop'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'shop_name_required')
        self.assertEqual(Profile.objects.get(user=self.user).account_type, 'private')

    def test_blank_name_does_not_count(self):
        response = self.client.patch(self.url, {'account_type': 'shop', 'shop_name': '   '}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_switch_to_shop_with_name(self):
        response = self.client.patch(
            self.url, {'account_type': 'shop', 'shop_name': 'Прокат Юнусабад', 'working_hours': 'Пн–Сб 10–20'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data['account_type'], 'shop')
        self.assertEqual(data['listing_limit'], 200)
        self.assertEqual(data['working_hours'], 'Пн–Сб 10–20')

    def test_shop_cannot_erase_its_name(self):
        set_profile(self.user, account_type='shop', shop_name='Прокат')
        response = self.client.patch(self.url, {'shop_name': ''}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'shop_name_required')

    def test_shop_can_switch_back(self):
        set_profile(self.user, account_type='shop', shop_name='Прокат')
        response = self.client.patch(self.url, {'account_type': 'private'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['account_type'], 'private')

    def test_unknown_type_rejected(self):
        response = self.client.patch(self.url, {'account_type': 'admin'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_public_page_shows_badge_and_hours_only_for_shop(self):
        profile = set_profile(self.user, shop_name='Прокат', working_hours='10–20')
        url = reverse('public-user-detail', kwargs={'pk': self.user.pk})
        data = self.client.get(url).json()
        self.assertEqual(data['account_type'], 'private')
        self.assertEqual(data['working_hours'], '')

        profile.account_type = 'shop'
        profile.save()
        data = self.client.get(url).json()
        self.assertEqual(data['account_type'], 'shop')
        self.assertEqual(data['working_hours'], '10–20')

    def test_listing_card_carries_owner_type(self):
        set_profile(self.user, account_type='shop', shop_name='Прокат')
        make_item(self.user)
        rows = self.client.get(reverse('listing-list-create')).json()
        rows = rows.get('results', rows)
        self.assertEqual(rows[0]['owner']['account_type'], 'shop')


@override_settings(LISTING_LIMIT_PRIVATE=2, LISTING_LIMIT_SHOP=3)
class ListingLimitTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.category, _ = Category.objects.get_or_create(slug='test-limit', defaults={'name': 'Test'})

    def create(self):
        return self.client.post(reverse('listing-list-create'), listing_payload(self.category), format='json')

    def test_private_stops_at_limit(self):
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create().status_code, 201)
        response = self.create()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'listing_limit')
        self.assertEqual(Item.objects.filter(owner=self.user).count(), 2)

    def test_legacy_create_endpoint_also_limited(self):
        make_item(self.user)
        make_item(self.user)
        response = self.client.post(reverse('item-create'), listing_payload(self.category), format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'listing_limit')

    def test_inactive_and_rejected_do_not_count(self):
        for status in (Item.STATUS_INACTIVE, Item.STATUS_REJECTED, Item.STATUS_INACTIVE):
            item = make_item(self.user)
            item.status = status
            item.save()
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create().status_code, 201)

    def test_shop_gets_more(self):
        set_profile(self.user, account_type='shop', shop_name='Прокат')
        for _ in range(3):
            self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create().json()['code'], 'listing_limit')

    def test_reviving_a_withdrawn_listing_counts(self):
        make_item(self.user)
        make_item(self.user)
        withdrawn = make_item(self.user)
        withdrawn.status = Item.STATUS_INACTIVE
        withdrawn.save()
        url = reverse('listing-detail', kwargs={'pk': withdrawn.pk})
        response = self.client.patch(url, {'status': 'pending'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'listing_limit')
        withdrawn.refresh_from_db()
        self.assertEqual(withdrawn.status, Item.STATUS_INACTIVE)

    def test_editing_a_live_listing_is_not_blocked(self):
        first = make_item(self.user)
        make_item(self.user)
        url = reverse('listing-detail', kwargs={'pk': first.pk})
        response = self.client.patch(url, {'price_per_day': '70000'}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_switching_back_keeps_existing_listings(self):
        set_profile(self.user, account_type='shop', shop_name='Прокат')
        for _ in range(3):
            self.create()
        self.client.patch(reverse('user-profile'), {'account_type': 'private'}, format='json')
        self.assertEqual(Item.objects.filter(owner=self.user, status=Item.STATUS_PENDING).count(), 3)
        self.assertEqual(self.create().json()['code'], 'listing_limit')
        data = self.client.get(reverse('user-profile')).json()
        self.assertEqual((data['listing_limit'], data['live_listings']), (2, 3))


class ShopStatsTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.url = reverse('my-listings-stats')

    def test_private_gets_403(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'shop_only')

    def test_anonymous_gets_401(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_shop_sees_own_listings_only(self):
        set_profile(self.user, account_type='shop', shop_name='Прокат')
        item = make_item(self.user)
        Item.objects.filter(pk=item.pk).update(view_count=7, favorite_count=2)
        hidden = make_item(self.user)
        hidden.status = Item.STATUS_INACTIVE
        hidden.save()
        make_item(make_user())  # чужое

        renter = make_user()
        make_booking(item, renter, status=Booking.STATUS_DRAFT)
        make_booking(item, renter, status=Booking.STATUS_PENDING_PAYMENT)
        make_booking(item, renter, status=Booking.STATUS_COMPLETED)

        data = self.client.get(self.url).json()
        self.assertEqual(data['totals'], {'listings': 1, 'views': 7, 'favorites': 2, 'requests': 2, 'deals': 1})
        self.assertEqual([row['id'] for row in data['listings']], [item.pk])


@override_settings(LISTING_LIMIT_PRIVATE=2)
class GrandfatherMigrationTests(APITestCase):
    def test_big_sellers_become_shops(self):
        import importlib

        from django.apps import apps as django_apps

        migration = importlib.import_module('apps.users.migrations.0009_profile_account_type')
        big, small = make_user(), make_user()
        for _ in range(3):
            make_item(big)
        make_item(small)
        withdrawn = make_item(small)
        withdrawn.status = Item.STATUS_INACTIVE
        withdrawn.save()

        migration.grandfather_big_sellers(django_apps, None)

        self.assertEqual(Profile.objects.get(user=big).account_type, 'shop')
        self.assertEqual(Profile.objects.get(user=small).account_type, 'private')

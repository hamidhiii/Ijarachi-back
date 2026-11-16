"""DEAL_FLOW_ENABLED=False: сделка, торг и их задачи выключены, но не удалены."""
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.bookings import tasks
from apps.bookings.models import Booking
from apps.bookings.testing import make_booking, make_item, make_paid_booking, make_user
from apps.catalog.models import Item


@override_settings(DEAL_FLOW_ENABLED=False)
class DealFlowDisabledTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.renter = make_user()
        self.item = make_item(self.owner)
        self.deal = make_booking(self.item, self.renter)
        self.client.force_authenticate(self.renter)

    def assertGone(self, response):
        self.assertEqual(response.status_code, 410, getattr(response, 'data', None))
        self.assertEqual(response.data['code'], 'DEAL_FLOW_DISABLED')

    def test_deal_endpoints_are_gone(self):
        pk = {'pk': self.deal.pk}
        calls = [
            ('post', reverse('deal-create'), {'item': self.item.pk}),
            ('get', reverse('deal-create'), None),
            ('post', reverse('deal-preview'), {'item': self.item.pk}),
            ('get', reverse('pricing-payout'), {'price_per_day': 1000, 'days': 1}),
            ('get', reverse('deal-list'), None),
            ('get', reverse('my-rentals'), None),
            ('get', reverse('deal-detail', kwargs=pk), None),
            ('post', reverse('deal-pay', kwargs=pk), {'provider': 'cash'}),
            ('post', reverse('deal-review', kwargs=pk), {}),
            ('post', reverse('deal-confirm-return', kwargs=pk), {}),
            ('post', reverse('deal-dispute', kwargs=pk), {}),
            ('post', reverse('deal-resolve-dispute', kwargs=pk), {}),
            ('patch', reverse('deal-status', kwargs=pk), {'status': 'cancelled'}),
            ('post', reverse('booking-create'), {}),
            ('get', reverse('booking-detail', kwargs=pk), None),
            ('post', reverse('offer-list-create'), {'item': self.item.pk, 'amount': 100}),
            ('get', reverse('offer-list-create'), None),
            ('post', reverse('offer-respond', kwargs={'pk': 1}), {'action': 'accept'}),
        ]
        for method, url, data in calls:
            with self.subTest(method=method, url=url):
                self.assertGone(getattr(self.client, method)(url, data, format='json'))
        self.deal.refresh_from_db()
        self.assertEqual(self.deal.status, Booking.STATUS_DRAFT)

    def test_anonymous_also_gets_410_not_401(self):
        self.client.force_authenticate(None)
        self.assertGone(self.client.get(reverse('deal-list')))

    @override_settings(PAYMENTS_MODE='live')
    def test_deal_payment_webhooks_are_gone(self):
        for name in ('payme-webhook', 'click-webhook'):
            with self.subTest(name=name):
                self.assertGone(self.client.post(reverse(name), {}, format='json'))

    def test_listing_board_endpoints_still_work(self):
        self.assertEqual(self.client.get(reverse('listing-list-create')).status_code, 200)
        self.assertEqual(self.client.get(reverse('listing-detail', kwargs={'pk': self.item.pk})).status_code, 200)
        self.assertEqual(self.client.get(reverse('user-reviews', kwargs={'pk': self.owner.pk})).status_code, 200)

    def test_deal_data_is_kept(self):
        self.assertTrue(Booking.objects.filter(pk=self.deal.pk).exists())
        self.assertTrue(Item.objects.filter(pk=self.item.pk).exists())


@override_settings(DEAL_FLOW_ENABLED=False)
class DealTasksSkippedTests(APITestCase):
    def test_periodic_deal_tasks_do_nothing(self):
        owner, renter = make_user(), make_user()
        booking = make_paid_booking(make_item(owner), renter, status=Booking.STATUS_COMPLETED)

        with mock.patch('apps.bookings.settlement.settle_completed_booking') as settle, \
                mock.patch('apps.notifications.tasks.create_notification') as notify:
            tasks.release_escrow.delay(booking.pk)
            tasks.expire_stale_bookings.delay()
            tasks.notify_expiring_bookings.delay()
            tasks.notify_owner_new_booking.delay(booking.pk)

        settle.assert_not_called()
        notify.assert_not_called()
        booking.refresh_from_db()
        self.assertEqual(booking.escrow_status, Booking.ESCROW_HELD)

    @override_settings(DEAL_FLOW_ENABLED=True)
    def test_tasks_run_when_flag_is_on(self):
        with mock.patch('apps.bookings.settlement.settle_completed_booking') as settle:
            tasks.release_escrow.delay(42)
        settle.assert_called_once_with(42)

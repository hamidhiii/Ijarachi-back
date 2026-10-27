"""Занятость дат считается по активным броням, а не по общему списку дат."""
import threading
from datetime import date

from django.core.cache import cache
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from apps.bookings.availability import blocked_dates, is_range_free
from apps.bookings.models import Booking
from apps.bookings.tasks import expire_stale_bookings
from apps.bookings.testing import make_booking, make_item, make_paid_booking, make_user
from apps.catalog.models import ItemAvailability
from apps.payments.models import Payment

JUNE_10, JUNE_12 = date(2030, 6, 10), date(2030, 6, 12)


class OccupancyTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.item = make_item(self.owner)
        self.renter_a = make_user()
        self.renter_b = make_user()

    def _status(self, user, booking, new_status):
        self.client.force_authenticate(user)
        return self.client.patch(
            reverse('deal-status', kwargs={'pk': booking.pk}), {'status': new_status}, format='json',
        )

    def test_cancelling_a_draft_keeps_dates_of_a_paid_booking(self):
        # Черновик B заведён, пока даты были свободны; потом A оплатил те же дни.
        draft_b = make_booking(self.item, self.renter_b)
        make_paid_booking(self.item, self.renter_a)

        response = self._status(self.renter_b, draft_b, 'cancelled')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(is_range_free(self.item, JUNE_10, JUNE_12))
        self.assertIn('2030-06-11', blocked_dates(self.item))

    def test_expired_draft_keeps_dates_of_a_paid_booking(self):
        draft_b = make_booking(self.item, self.renter_b)
        Booking.objects.filter(pk=draft_b.pk).update(updated_at=date(2020, 1, 1))
        make_paid_booking(self.item, self.renter_a)

        expire_stale_bookings()

        draft_b.refresh_from_db()
        self.assertEqual(draft_b.status, Booking.STATUS_CANCELLED)
        self.assertFalse(is_range_free(self.item, JUNE_10, JUNE_12))

    def test_cancelling_a_booking_frees_only_its_own_dates(self):
        paid_a = make_paid_booking(self.item, self.renter_a)
        paid_b = make_paid_booking(self.item, self.renter_b, start=date(2030, 7, 1), end=date(2030, 7, 3))

        response = self._status(self.renter_b, paid_b, 'cancelled')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(is_range_free(self.item, date(2030, 7, 1), date(2030, 7, 3)))
        self.assertFalse(is_range_free(self.item, paid_a.start_date, paid_a.end_date))

    def test_owner_calendar_patch_cannot_free_booked_dates(self):
        make_paid_booking(self.item, self.renter_a)
        self.client.force_authenticate(self.owner)

        response = self.client.patch(
            reverse('listing-availability', kwargs={'pk': self.item.pk}),
            {'blocked_dates': ['2030-06-11', '2030-08-01']}, format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        # Бронь по-прежнему занимает свои дни, а в ручной список попал только 1 августа.
        self.assertFalse(is_range_free(self.item, JUNE_10, JUNE_12))
        self.assertEqual(ItemAvailability.objects.get(item=self.item).blocked_dates, ['2030-08-01'])
        self.assertEqual(response.data['manual_blocked_dates'], ['2030-08-01'])
        self.assertIn('2030-06-10', response.data['booked_dates'])

    def test_manual_block_makes_dates_unavailable(self):
        ItemAvailability.objects.create(item=self.item, blocked_dates=['2030-06-11'])
        self.client.force_authenticate(self.renter_a)

        response = self.client.post(reverse('deal-create'), {
            'item': self.item.pk, 'start_date': '2030-06-10', 'end_date': '2030-06-12',
        }, format='json')

        self.assertEqual(response.status_code, 400)

    def test_pay_on_occupied_dates_is_409(self):
        make_paid_booking(self.item, self.renter_a)
        draft_b = make_booking(self.item, self.renter_b)
        self.client.force_authenticate(self.renter_b)

        response = self.client.post(reverse('deal-pay', kwargs={'pk': draft_b.pk}), {'provider': 'cash'}, format='json')

        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['code'], 'DATES_UNAVAILABLE')

    def test_paying_again_does_not_conflict_with_own_dates(self):
        draft = make_booking(self.item, self.renter_a)
        self.client.force_authenticate(self.renter_a)
        url = reverse('deal-pay', kwargs={'pk': draft.pk})

        first = self.client.post(url, {'provider': 'cash'}, format='json')
        second = self.client.post(url, {'provider': 'cash'}, format='json')

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)

    def test_draft_does_not_occupy_dates(self):
        make_booking(self.item, self.renter_a)
        self.assertTrue(is_range_free(self.item, JUNE_10, JUNE_12))

    @override_settings(BOOKING_MAX_DAYS=30)
    def test_rental_longer_than_limit_is_rejected(self):
        self.client.force_authenticate(self.renter_a)
        response = self.client.post(reverse('deal-create'), {
            'item': self.item.pk, 'start_date': '2030-01-01', 'end_date': '2030-12-31',
        }, format='json')
        self.assertEqual(response.status_code, 400)


class ConcurrentBookingTests(TransactionTestCase):
    """Две оплаты одних дат одновременно: ровно одна занимает даты, вторая — 409."""

    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.item = make_item(self.owner)
        self.renters = [make_user(), make_user()]
        self.drafts = [make_booking(self.item, renter) for renter in self.renters]

    def _run_in_parallel(self, calls):
        barrier = threading.Barrier(len(calls))
        results = [None] * len(calls)

        def worker(index, call):
            try:
                barrier.wait()
                results[index] = call()
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(i, call)) for i, call in enumerate(calls)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return results

    def _pay(self, renter, draft, provider):
        def call():
            client = APIClient()
            client.force_authenticate(renter)
            return client.post(reverse('deal-pay', kwargs={'pk': draft.pk}), {'provider': provider}, format='json')
        return call

    def _assert_single_winner(self, responses):
        codes = sorted(response.status_code for response in responses)
        self.assertEqual(codes, [201, 409], [getattr(r, 'data', r) for r in responses])
        occupying = Booking.objects.filter(
            item=self.item, status__in=[Booking.STATUS_PENDING_PAYMENT, Booking.STATUS_PAID],
        )
        self.assertEqual(occupying.count(), 1)

    def test_parallel_cash_payments_for_same_dates(self):
        responses = self._run_in_parallel([
            self._pay(renter, draft, 'cash') for renter, draft in zip(self.renters, self.drafts)
        ])
        self._assert_single_winner(responses)

    def test_parallel_stub_payments_for_same_dates(self):
        responses = self._run_in_parallel([
            self._pay(renter, draft, 'payme') for renter, draft in zip(self.renters, self.drafts)
        ])
        self._assert_single_winner(responses)
        self.assertEqual(Payment.objects.filter(status=Payment.STATUS_PAID).count(), 1)

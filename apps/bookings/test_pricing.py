"""Модель комиссии B, цена из торга, даты брони."""
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.bookings.models import Booking
from apps.bookings.settlement import settle_completed_booking
from apps.bookings.testing import make_item, make_paid_booking, make_user
from apps.catalog.models import Item, Offer
from apps.users.models import Profile


def future(days):
    return (timezone.localdate() + timedelta(days=days)).isoformat()


@override_settings(PLATFORM_COMMISSION_PERCENT=15)
class CommissionModelBTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.renter = make_user()
        self.item = make_item(self.owner)  # 100 000 сум/сутки, залог 50 000
        self.client.force_authenticate(self.renter)

    def _preview(self, start=10, end=12):
        return self.client.post(reverse('deal-preview'), {
            'item': self.item.pk, 'start_date': future(start), 'end_date': future(end),
        }, format='json')

    def test_renter_pays_rent_plus_deposit_without_commission_on_top(self):
        response = self._preview()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Decimal(response.data['total_price']), Decimal('350000'))
        self.assertEqual(Decimal(response.data['commission_amount']), Decimal('45000'))
        self.assertEqual(Decimal(response.data['owner_payout']), Decimal('255000'))

    def test_created_deal_stores_model_b_numbers(self):
        response = self.client.post(reverse('deal-create'), {
            'item': self.item.pk, 'start_date': future(10), 'end_date': future(12),
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        deal = Booking.objects.get(pk=response.data['id'])
        self.assertEqual(deal.total_price, Decimal('350000'))
        self.assertEqual(deal.commission_amount, Decimal('45000'))
        self.assertEqual(Decimal(response.data['owner_payout']), Decimal('255000'))

    def test_payout_uses_commission_fixed_in_the_deal(self):
        booking = make_paid_booking(self.item, self.renter, status=Booking.STATUS_COMPLETED)

        with override_settings(PLATFORM_COMMISSION_PERCENT=30):
            settle_completed_booking(booking.pk)

        self.assertEqual(Profile.objects.get(user=self.owner).wallet_balance, Decimal('255000'))

    def test_payout_preview_for_owner(self):
        self.client.force_authenticate(None)
        response = self.client.get(reverse('pricing-payout'), {'price_per_day': 100000, 'days': 2})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['commission_percent'], 15)
        self.assertEqual(Decimal(response.data['owner_payout']), Decimal('170000'))

    def test_accepted_offer_sets_deal_price(self):
        offer = Offer.objects.create(
            item=self.item, renter=self.renter, amount=Decimal('80000'), status=Offer.STATUS_ACCEPTED,
        )

        response = self.client.post(reverse('deal-create'), {
            'item': self.item.pk, 'start_date': future(10), 'end_date': future(12),
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        deal = Booking.objects.get(pk=response.data['id'])
        self.assertEqual(deal.price_per_day, Decimal('80000'))
        self.assertEqual(deal.offer_id, offer.pk)
        # Комиссия — от согласованной цены: 240 000 × 15 %.
        self.assertEqual(deal.commission_amount, Decimal('36000'))
        self.assertEqual(deal.total_price, Decimal('290000'))

    def test_pending_or_other_renters_offer_does_not_change_price(self):
        Offer.objects.create(item=self.item, renter=self.renter, amount=Decimal('80000'), status=Offer.STATUS_PENDING)
        Offer.objects.create(item=self.item, renter=make_user(), amount=Decimal('50000'), status=Offer.STATUS_ACCEPTED)

        response = self._preview()

        self.assertEqual(Decimal(response.data['price_per_day']), Decimal('100000'))
        self.assertIsNone(response.data['offer_id'])

    def test_new_bid_after_acceptance_reopens_negotiation(self):
        Offer.objects.create(item=self.item, renter=self.renter, amount=Decimal('80000'), status=Offer.STATUS_ACCEPTED)
        Offer.objects.create(item=self.item, renter=self.renter, amount=Decimal('70000'), status=Offer.STATUS_PENDING)

        response = self._preview()

        self.assertEqual(Decimal(response.data['price_per_day']), Decimal('100000'))


class RentalDateRulesTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.renter = make_user()
        self.item = make_item(self.owner)
        self.client.force_authenticate(self.renter)

    def _create(self, start, end):
        return self.client.post(reverse('deal-create'), {
            'item': self.item.pk, 'start_date': start, 'end_date': end,
        }, format='json')

    def test_start_in_the_past_is_rejected(self):
        self.assertEqual(self._create(future(-1), future(2)).status_code, 400)

    def test_today_is_allowed(self):
        self.assertEqual(self._create(future(0), future(1)).status_code, 201)

    def test_shorter_than_min_rental_days_is_rejected(self):
        Item.objects.filter(pk=self.item.pk).update(min_rental_days=3)
        self.assertEqual(self._create(future(5), future(6)).status_code, 400)
        self.assertEqual(self._create(future(5), future(7)).status_code, 201)

    def test_preview_applies_the_same_rules(self):
        response = self.client.post(reverse('deal-preview'), {
            'item': self.item.pk, 'start_date': future(-3), 'end_date': future(1),
        }, format='json')
        self.assertEqual(response.status_code, 400)

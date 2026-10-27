"""Повторная модерация после правки и правила торга."""
import shutil
import tempfile
from decimal import Decimal

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.bookings.testing import make_item, make_user
from apps.catalog.models import Item, Offer

TEST_MEDIA_ROOT = tempfile.mkdtemp()
GIF = (
    b'GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00\xff\xff\xff,'
    b'\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02L\x01\x00;'
)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class RemoderationTests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.item = make_item(self.owner)
        self.url = reverse('listing-detail', kwargs={'pk': self.item.pk})

    def _patch(self, user, data):
        self.client.force_authenticate(user)
        return self.client.patch(self.url, data, format='json')

    def test_editing_text_sends_listing_back_to_moderation(self):
        response = self._patch(self.owner, {'description': 'Звоните +998 90 000 00 00'})

        self.assertEqual(response.status_code, 200, response.data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, Item.STATUS_PENDING)

    def test_editing_price_keeps_listing_published(self):
        response = self._patch(self.owner, {'price_per_day': '90000'})

        self.assertEqual(response.status_code, 200, response.data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, Item.STATUS_APPROVED)

    def test_same_text_does_not_trigger_moderation(self):
        self._patch(self.owner, {'title': self.item.title})
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, Item.STATUS_APPROVED)

    def test_staff_edit_keeps_listing_published(self):
        staff = make_user(is_staff=True)
        Item.objects.filter(pk=self.item.pk).update(owner=staff)
        self._patch(staff, {'title': 'Исправлено модератором'})
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, Item.STATUS_APPROVED)

    def test_new_photo_sends_listing_back_to_moderation(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            reverse('listing-photo-upload', kwargs={'item_id': self.item.pk}),
            {'image': SimpleUploadedFile('a.gif', GIF, content_type='image/gif')},
            format='multipart',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, Item.STATUS_PENDING)

    def test_update_rejects_zero_price(self):
        response = self._patch(self.owner, {'price_per_day': '0'})
        self.assertEqual(response.status_code, 400)


class OfferRulesTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.renter = make_user()
        self.item = make_item(self.owner)
        Item.objects.filter(pk=self.item.pk).update(is_negotiable=True)

    def _offer(self, amount):
        self.client.force_authenticate(self.renter)
        return self.client.post(reverse('offer-list-create'), {'item': self.item.pk, 'amount': amount}, format='json')

    def test_offer_amount_must_be_positive(self):
        self.assertEqual(self._offer('0').status_code, 400)
        self.assertEqual(self._offer('-5').status_code, 400)
        self.assertFalse(Offer.objects.exists())

    def test_one_pending_offer_per_thread(self):
        self.assertEqual(self._offer('80000').status_code, 201)

        response = self._offer('70000')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'offer_pending_exists')
        self.assertEqual(Offer.objects.count(), 1)

    def test_new_bid_allowed_after_answer(self):
        offer = Offer.objects.create(item=self.item, renter=self.renter, amount=Decimal('80000'), status=Offer.STATUS_REJECTED)
        self.assertEqual(self._offer('85000').status_code, 201, offer)

    def test_counter_amount_must_be_positive(self):
        offer = Offer.objects.create(item=self.item, renter=self.renter, amount=Decimal('80000'))
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            reverse('offer-respond', kwargs={'pk': offer.pk}), {'action': 'counter', 'amount': '-1'}, format='json',
        )

        self.assertEqual(response.status_code, 400)

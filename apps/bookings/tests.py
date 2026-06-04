from datetime import date
from decimal import Decimal
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.bookings.models import Booking, BookingPhoto
from apps.catalog.models import Category, Item


TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class BookingPhotoUploadTests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(phone='+998900000011')
        self.renter = user_model.objects.create_user(phone='+998900000012')
        self.category = Category.objects.create(name='Decor', slug='deal-photos-decor')
        self.item = Item.objects.create(
            owner=self.owner,
            category=self.category,
            title='Wedding chairs',
            description='Chair set',
            price_per_day=Decimal('100000'),
            deposit=Decimal('50000'),
            condition=Item.CONDITION_GOOD,
            status=Item.STATUS_APPROVED,
            address='Tashkent',
            city='Tashkent',
        )
        self.booking = Booking.objects.create(
            item=self.item,
            renter=self.renter,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 12),
            price_per_day=Decimal('100000'),
            deposit_amount=Decimal('50000'),
            commission_amount=Decimal('30000'),
            total_price=Decimal('380000'),
            escrow_amount=Decimal('380000'),
            status=Booking.STATUS_DRAFT,
        )
        self.url = reverse('deal-photo-upload', kwargs={'pk': self.booking.pk})

    def _image(self):
        return SimpleUploadedFile(
            'evidence.gif',
            b'GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00\xff\xff\xff,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02L\x01\x00;',
            content_type='image/gif',
        )

    def test_photo_upload_is_blocked_before_payment(self):
        self.client.force_authenticate(self.renter)

        response = self.client.post(
            self.url,
            {'kind': BookingPhoto.KIND_BEFORE, 'image': self._image()},
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(BookingPhoto.objects.count(), 0)

    def test_paid_deal_party_can_upload_photo_and_see_it_in_detail(self):
        self.booking.status = Booking.STATUS_PAID
        self.booking.save(update_fields=['status'])
        self.client.force_authenticate(self.renter)

        response = self.client.post(
            self.url,
            {'kind': BookingPhoto.KIND_BEFORE, 'comment': 'Before handoff', 'image': self._image()},
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(BookingPhoto.objects.count(), 1)

        detail_response = self.client.get(reverse('deal-detail', kwargs={'pk': self.booking.pk}))

        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(detail_response.data['photos']), 1)
        self.assertEqual(detail_response.data['photos'][0]['kind'], BookingPhoto.KIND_BEFORE)

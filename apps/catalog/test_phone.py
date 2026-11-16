"""«Показать номер»: только авторизованным, каждое нажатие в журнале, дубли за 24 ч не считаются."""
from datetime import timedelta

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.bookings.testing import make_item, make_user
from apps.catalog.models import Item, PhoneReveal


class PhoneRevealTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.item = make_item(self.owner)
        self.renter = make_user()
        self.url = reverse('listing-phone', kwargs={'pk': self.item.pk})

    def test_anonymous_gets_401(self):
        self.assertEqual(self.client.post(self.url).status_code, 401)
        self.assertFalse(PhoneReveal.objects.exists())

    def test_returns_owner_phone_and_logs(self):
        self.client.force_authenticate(self.renter)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()['phone'], response.json()['owner_id']), (self.owner.phone, self.owner.pk))
        reveal = PhoneReveal.objects.get()
        self.assertEqual((reveal.item, reveal.user, reveal.counted), (self.item, self.renter, True))

    def test_repeat_within_24h_is_logged_but_not_counted(self):
        self.client.force_authenticate(self.renter)
        self.client.post(self.url)
        self.client.post(self.url)
        self.assertEqual(PhoneReveal.objects.count(), 2)
        self.assertEqual(PhoneReveal.objects.filter(counted=True).count(), 1)

    def test_counted_again_after_24h(self):
        self.client.force_authenticate(self.renter)
        self.client.post(self.url)
        PhoneReveal.objects.update(created_at=timezone.now() - timedelta(hours=25))
        self.client.post(self.url)
        self.assertEqual(PhoneReveal.objects.filter(counted=True).count(), 2)

    def test_other_users_count_separately(self):
        for user in (self.renter, make_user()):
            self.client.force_authenticate(user)
            self.client.post(self.url)
        self.assertEqual(PhoneReveal.objects.filter(counted=True).count(), 2)

    def test_owner_click_is_not_counted(self):
        self.client.force_authenticate(self.owner)
        self.client.post(self.url)
        self.assertEqual(PhoneReveal.objects.get().counted, False)

    def test_unpublished_listing_is_404(self):
        Item.objects.filter(pk=self.item.pk).update(status=Item.STATUS_PENDING)
        self.client.force_authenticate(self.renter)
        self.assertEqual(self.client.post(self.url).status_code, 404)

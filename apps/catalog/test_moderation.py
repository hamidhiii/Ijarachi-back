"""Жалобы, очередь модерации, скрытие объявления, значок «Проверен MyID»."""
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.bookings.testing import make_item, make_user
from apps.catalog.models import Item, Report
from apps.users.models import Profile


class ReportTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.item = make_item(self.owner)
        self.user = make_user()
        self.url = reverse('listing-report', kwargs={'pk': self.item.pk})

    def test_report_once_per_user(self):
        self.client.force_authenticate(self.user)
        first = self.client.post(self.url, {'reason': 'fraud', 'comment': 'Просит предоплату на карту'}, format='json')
        self.assertEqual(first.status_code, 201, first.content)
        again = self.client.post(self.url, {'reason': 'other'}, format='json')
        self.assertEqual((again.status_code, again.json()['id']), (200, first.json()['id']))
        self.assertEqual(Report.objects.count(), 1)

    def test_validation(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(self.url, {'reason': 'nonsense'}, format='json').status_code, 400)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(self.url, {'reason': 'fraud'}, format='json').json()['code'], 'own_listing')
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(self.url, {'reason': 'fraud'}, format='json').status_code, 401)


class ModerationQueueTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.staff = make_user()
        self.staff.is_staff = True
        self.staff.save()
        self.owner = make_user()
        self.reported = make_item(self.owner)
        self.pending = make_item(self.owner, status=Item.STATUS_PENDING)
        make_item(self.owner)  # обычное — не в очереди
        for reporter in (make_user(), make_user()):
            Report.objects.create(item=self.reported, reporter=reporter, reason='fraud')
        self.client.force_authenticate(self.staff)

    def test_queue_has_reported_first_then_pending(self):
        rows = self.client.get(reverse('moderation-queue')).json()['results']
        self.assertEqual([(r['id'], r['open_reports']) for r in rows], [(self.reported.pk, 2), (self.pending.pk, 0)])

    def test_only_staff(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get(reverse('moderation-queue')).status_code, 403)
        self.assertEqual(self.client.get(reverse('moderation-reports')).status_code, 403)

    def test_hide_from_report_closes_all_reports(self):
        report = Report.objects.first()
        url = reverse('moderation-report-resolve', kwargs={'pk': report.pk})
        response = self.client.post(url, {'action': 'hide', 'comment': 'Мошенник'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.reported.refresh_from_db()
        self.assertEqual(self.reported.status, Item.STATUS_BLOCKED)
        self.assertEqual(Report.objects.filter(status=Report.STATUS_ACTION_TAKEN).count(), 2)
        self.assertEqual(self.client.get(reverse('listing-detail', kwargs={'pk': self.reported.pk})).status_code, 404)

    def test_dismiss_keeps_listing(self):
        report = Report.objects.first()
        self.client.post(reverse('moderation-report-resolve', kwargs={'pk': report.pk}), {'action': 'dismiss'}, format='json')
        report.refresh_from_db()
        self.assertEqual(report.status, Report.STATUS_DISMISSED)
        self.assertEqual(Item.objects.get(pk=self.reported.pk).status, Item.STATUS_APPROVED)

    def test_hide_and_unhide(self):
        url = reverse('moderation-listing-hide', kwargs={'pk': self.pending.pk})
        self.assertEqual(self.client.post(url, {'reason': 'Запрещённая вещь'}, format='json').json()['status'], 'blocked')
        self.assertEqual(self.client.delete(url).json()['status'], 'approved')

    def test_owner_cannot_unblock_or_escape_by_deleting(self):
        self.client.post(reverse('moderation-listing-hide', kwargs={'pk': self.reported.pk}), {'reason': 'x'}, format='json')
        self.client.force_authenticate(self.owner)
        url = reverse('listing-detail', kwargs={'pk': self.reported.pk})
        self.assertEqual(self.client.patch(url, {'status': 'pending'}, format='json').status_code, 400)
        self.client.delete(url)
        self.assertEqual(Item.objects.get(pk=self.reported.pk).status, Item.STATUS_BLOCKED)
        # Не считается в лимите: на FREE есть место.
        from apps.catalog.limits import live_listing_count

        self.assertEqual(live_listing_count(self.owner), 2)


class MyIDBadgeTests(APITestCase):
    def test_badge_after_myid(self):
        owner = make_user()
        item = make_item(owner)
        card = self.client.get(reverse('listing-detail', kwargs={'pk': item.pk})).json()
        self.assertFalse(card['owner']['myid_verified'])

        self.client.force_authenticate(owner)
        self.assertEqual(self.client.post(reverse('kyc-myid-stub-verify')).status_code, 200)
        self.assertIsNotNone(Profile.objects.get(user=owner).myid_verified_at)

        self.client.force_authenticate(None)
        card = self.client.get(reverse('listing-detail', kwargs={'pk': item.pk})).json()
        self.assertTrue(card['owner']['myid_verified'])
        rows = self.client.get(reverse('listing-list-create')).json()['results']
        self.assertTrue(rows[0]['owner']['myid_verified'])
        self.assertTrue(self.client.get(reverse('public-user-detail', kwargs={'pk': owner.pk})).json()['myid_verified'])

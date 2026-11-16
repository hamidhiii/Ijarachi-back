"""Кабинет владельца: брони с количеством, клиенты, остатки, сотрудники, филиалы, статистика, выгрузка."""
import threading
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.billing.models import Plan
from apps.billing.testing import give_plan
from apps.bookings.testing import make_booking, make_item, make_user
from apps.catalog.models import Item, ItemAvailability, ListingDailyStat, PhoneReveal
from apps.chat.models import Conversation, Message
from apps.crm import tasks
from apps.crm.models import Branch, Client, Reservation, StaffMember
from apps.notifications.models import Notification


def day(offset):
    return timezone.localdate() + timedelta(days=offset)


class CrmTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.item = make_item(self.owner, quantity=10)
        self.client.force_authenticate(self.owner)

    def reserve(self, quantity, start=1, end=3, **extra):
        return self.client.post(reverse('owner-reservations'), {
            'listing': self.item.pk, 'quantity': quantity,
            'start_date': day(start).isoformat(), 'end_date': day(end).isoformat(), **extra,
        }, format='json')


class ReservationStockTests(CrmTestCase):
    def test_manual_reservation_with_new_client(self):
        response = self.reserve(4, source='instagram', client_name='Дилноза', client_phone='+998901112233', price=120000)
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual((body['quantity'], body['source'], body['status']), (4, 'instagram', 'booked'))
        self.assertEqual(body['client_info']['name'], 'Дилноза')
        reservation = Reservation.objects.get()
        self.assertEqual((reservation.owner, reservation.created_by), (self.owner, self.owner))
        # Второй раз тот же номер — тот же клиент, а не дубль.
        self.reserve(1, client_name='Дилноза', client_phone='+998901112233')
        self.assertEqual(Client.objects.count(), 1)

    def test_stock_is_quantity_minus_booked_with_overlap(self):
        self.assertEqual(self.reserve(6, 1, 3).status_code, 201)
        self.assertEqual(self.reserve(4, 3, 5).status_code, 201)  # день 3: 6 + 4 = 10
        response = self.reserve(1, 2, 3)
        self.assertEqual(response.status_code, 409)
        self.assertEqual((response.json()['code'], response.json()['free']), ('NOT_ENOUGH_STOCK', 0))
        self.assertEqual(self.reserve(4, 1, 2).status_code, 201)  # дни 1–2: 6 + 4

        stock = self.client.get(reverse('owner-stock'), {'date': day(4).isoformat()}).json()
        self.assertEqual(stock[0], {'id': self.item.pk, 'title': self.item.title, 'branch': None,
                                    'quantity': 10, 'booked': 4, 'free': 6})
        period = self.client.get(reverse('owner-stock'), {'from': day(1).isoformat(), 'to': day(5).isoformat()}).json()
        self.assertEqual(period[0]['free'], 0)

    def test_deal_bookings_take_one_unit(self):
        item = make_item(self.owner, quantity=2)
        make_booking(item, make_user(), start=day(1), end=day(2), status='paid')
        response = self.client.post(reverse('owner-reservations'), {
            'listing': item.pk, 'quantity': 2, 'start_date': day(1).isoformat(), 'end_date': day(1).isoformat(),
        }, format='json')
        self.assertEqual(response.json()['free'], 1)

    def test_manually_closed_day_has_no_stock(self):
        ItemAvailability.objects.create(item=self.item, blocked_dates=[day(2).isoformat()])
        self.assertEqual(self.reserve(1, 1, 3).json()['code'], 'NOT_ENOUGH_STOCK')

    def test_more_than_quantity_and_bad_dates(self):
        self.assertEqual(self.reserve(11).json()['code'], 'NOT_ENOUGH_STOCK')
        self.assertEqual(self.reserve(1, 5, 2).json()['code'], 'INVALID_DATES')

    def test_status_flow_and_freeing(self):
        reservation_id = self.reserve(10).json()['id']
        url = reverse('owner-reservation-detail', kwargs={'pk': reservation_id})
        self.assertEqual(self.client.patch(url, {'status': 'returned'}, format='json').json()['code'], 'INVALID_STATUS')
        self.assertEqual(self.client.patch(url, {'status': 'issued'}, format='json').status_code, 200)
        self.assertEqual(self.reserve(1).status_code, 409)
        self.assertEqual(self.client.patch(url, {'status': 'returned'}, format='json').status_code, 200)
        self.assertEqual(self.reserve(1).status_code, 201)

    def test_editing_rechecks_without_counting_itself(self):
        reservation_id = self.reserve(8).json()['id']
        self.reserve(2, 4, 6)
        url = reverse('owner-reservation-detail', kwargs={'pk': reservation_id})
        self.assertEqual(self.client.patch(url, {'quantity': 10}, format='json').status_code, 200)
        self.assertEqual(self.client.patch(url, {'end_date': day(4).isoformat()}, format='json').status_code, 409)

    def test_delete_cancels(self):
        reservation_id = self.reserve(10).json()['id']
        self.assertEqual(self.client.delete(reverse('owner-reservation-detail', kwargs={'pk': reservation_id})).status_code, 204)
        self.assertEqual(Reservation.objects.get().status, 'cancelled')
        self.assertEqual(self.reserve(10).status_code, 201)

    def test_quantity_cannot_drop_below_booked(self):
        self.reserve(7, 1, 2)
        url = reverse('listing-detail', kwargs={'pk': self.item.pk})
        self.assertEqual(self.client.patch(url, {'quantity': 6}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'quantity': 7}, format='json').status_code, 200)

    def test_public_calendar_blocks_only_fully_booked_days(self):
        self.reserve(10, 1, 1)
        self.reserve(3, 2, 2)
        blocked = self.client.get(reverse('listing-availability', kwargs={'pk': self.item.pk})).json()['booked_dates']
        self.assertEqual(blocked, [day(1).isoformat()])

    def test_owner_calendar(self):
        self.reserve(6, 1, 2, client_name='Азиз')
        cal = self.client.get(reverse('owner-listing-calendar', kwargs={'pk': self.item.pk}),
                              {'from': day(0).isoformat(), 'to': day(2).isoformat()}).json()
        self.assertEqual([(d['booked'], d['free']) for d in cal['days']], [(0, 10), (6, 4), (6, 4)])
        self.assertEqual(len(cal['reservations']), 1)

    def test_cannot_touch_someone_elses_listing(self):
        other = make_item(make_user(), quantity=5)
        response = self.client.post(reverse('owner-reservations'), {
            'listing': other.pk, 'quantity': 1, 'start_date': day(1).isoformat(), 'end_date': day(1).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(reverse('owner-listing-calendar', kwargs={'pk': other.pk})).status_code, 404)


class ClientBaseTests(CrmTestCase):
    def test_client_card_with_history_and_notes(self):
        rentoo_user = make_user()
        response = self.client.post(reverse('owner-clients'), {
            'name': 'Шахло', 'phone': rentoo_user.phone, 'notes': 'Берёт на свадьбы',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        client_id = response.json()['id']
        self.assertEqual(response.json()['rentoo_user_id'], rentoo_user.pk)
        self.reserve(2, client=client_id)
        self.reserve(1, 5, 6, client=client_id)

        card = self.client.get(reverse('owner-client-detail', kwargs={'pk': client_id})).json()
        self.assertEqual((card['reservations_count'], len(card['history'])), (2, 2))
        self.assertEqual(card['notes'], 'Берёт на свадьбы')
        self.assertEqual(self.client.get(reverse('owner-clients'), {'q': 'шах'}).json()['count'], 1)
        dup = self.client.post(reverse('owner-clients'), {'name': 'X', 'phone': rentoo_user.phone}, format='json')
        self.assertEqual(dup.json()['code'], 'CLIENT_EXISTS')

    def test_clients_are_private_to_the_account(self):
        Client.objects.create(owner=make_user(), name='Чужой')
        self.assertEqual(self.client.get(reverse('owner-clients')).json()['count'], 0)


class StaffAccessTests(CrmTestCase):
    def setUp(self):
        super().setUp()
        self.manager = make_user()
        self.viewer = make_user()

    def add_staff(self, user, role):
        return self.client.post(reverse('owner-staff'), {'phone': user.phone, 'role': role}, format='json')

    def as_staff(self, user):
        api = APIClient()
        api.force_authenticate(user)
        api.credentials(HTTP_X_OWNER_ACCOUNT=str(self.owner.pk))
        return api

    def test_staff_needs_business(self):
        response = self.add_staff(self.manager, 'manager')
        self.assertEqual((response.status_code, response.json()['required_plan']), (403, 'business'))

    def test_roles(self):
        give_plan(self.owner, Plan.BUSINESS)
        self.assertEqual(self.add_staff(self.manager, 'manager').status_code, 201)
        self.assertEqual(self.add_staff(self.viewer, 'viewer').status_code, 201)

        manager = self.as_staff(self.manager)
        created = manager.post(reverse('owner-reservations'), {
            'listing': self.item.pk, 'quantity': 1, 'start_date': day(1).isoformat(), 'end_date': day(1).isoformat(),
        }, format='json')
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(Reservation.objects.get().created_by, self.manager)
        self.assertEqual(manager.get(reverse('owner-staff')).json()['code'], 'OWNER_ONLY')

        viewer = self.as_staff(self.viewer)
        self.assertEqual(viewer.get(reverse('owner-reservations')).json()['count'], 1)
        denied = viewer.post(reverse('owner-clients'), {'name': 'X'}, format='json')
        self.assertEqual((denied.status_code, denied.json()['code']), (403, 'READ_ONLY_ROLE'))

        accounts = {row['id']: row['role'] for row in manager.get(reverse('owner-accounts')).json()}
        self.assertEqual(accounts, {self.manager.pk: 'owner', self.owner.pk: 'manager'})

    def test_stranger_cannot_open_the_cabinet(self):
        give_plan(self.owner, Plan.BUSINESS)
        response = self.as_staff(make_user()).get(reverse('owner-reservations'))
        self.assertEqual((response.status_code, response.json()['code']), (403, 'NOT_STAFF'))

    def test_access_suspended_when_plan_ends(self):
        give_plan(self.owner, Plan.BUSINESS)
        self.add_staff(self.manager, 'manager')
        from apps.billing.models import Subscription

        Subscription.objects.update(ends_at=timezone.now() - timedelta(minutes=1))
        response = self.as_staff(self.manager).get(reverse('owner-reservations'))
        self.assertEqual(response.json()['code'], 'STAFF_ACCESS_SUSPENDED')
        self.assertTrue(StaffMember.objects.exists())


class BranchTests(CrmTestCase):
    def test_branches_need_pro(self):
        give_plan(self.owner, Plan.BUSINESS)
        response = self.client.post(reverse('owner-branches'), {'name': 'Чиланзар'}, format='json')
        self.assertEqual(response.json()['required_plan'], 'pro')

    def test_branch_filter_for_stock_and_listings(self):
        give_plan(self.owner, Plan.PRO)
        branch_id = self.client.post(reverse('owner-branches'), {'name': 'Чиланзар'}, format='json').json()['id']
        other = make_item(self.owner, quantity=3)
        response = self.client.patch(reverse('owner-listing-detail', kwargs={'pk': other.pk}), {'branch': branch_id}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        listings = self.client.get(reverse('owner-listings'), {'branch': branch_id}).json()
        self.assertEqual([(row['id'], row['free_today']) for row in listings], [(other.pk, 3)])
        stock = self.client.get(reverse('owner-stock'), {'branch': branch_id}).json()
        self.assertEqual([row['id'] for row in stock], [other.pk])
        foreign_branch = Branch.objects.create(owner=make_user(), name='Чужая')
        bad = self.client.patch(reverse('owner-listing-detail', kwargs={'pk': other.pk}), {'branch': foreign_branch.pk}, format='json')
        self.assertEqual(bad.status_code, 400)


class StatsAndExportTests(CrmTestCase):
    def test_stats_need_business(self):
        self.assertEqual(self.client.get(reverse('owner-stats')).json()['code'], 'PLAN_FEATURE_REQUIRED')

    def test_monthly_stats(self):
        give_plan(self.owner, Plan.BUSINESS)
        renter = make_user()
        anon = APIClient()
        for _ in range(3):
            anon.get(reverse('listing-detail', kwargs={'pk': self.item.pk}))
        PhoneReveal.objects.create(item=self.item, user=renter, counted=True)
        PhoneReveal.objects.create(item=self.item, user=renter, counted=False)
        conversation = Conversation.objects.create(listing=self.item)
        conversation.participants.add(renter, self.owner)
        Message.objects.create(conversation=conversation, sender=renter, text='Есть на субботу?')
        Message.objects.create(conversation=conversation, sender=self.owner, text='Да')
        # Прошлый месяц не попадает в текущий.
        ListingDailyStat.objects.create(item=self.item, date=timezone.localdate().replace(day=1) - timedelta(days=1), views=50)

        data = self.client.get(reverse('owner-stats')).json()
        row = data['listings'][0]
        self.assertEqual((row['views'], row['phone_reveals'], row['chat_messages']), (3, 1, 1))
        self.assertEqual(data['totals']['views'], 3)
        self.assertEqual(len(data['by_month']), 6)
        self.assertEqual(data['by_month'][-2]['views'], 50)

    def test_export_needs_pro(self):
        give_plan(self.owner, Plan.BUSINESS)
        response = self.client.get(reverse('owner-export', kwargs={'entity': 'clients'}))
        self.assertEqual(response.json()['required_plan'], 'pro')

    def test_export_csv_and_xlsx(self):
        give_plan(self.owner, Plan.PRO)
        self.reserve(2, client_name='Мадина', client_phone='+998907770000')
        csv_response = self.client.get(reverse('owner-export', kwargs={'entity': 'reservations'}), {'type': 'csv'})
        self.assertEqual(csv_response.status_code, 200)
        text = csv_response.content.decode('utf-8-sig')
        self.assertIn('Мадина', text)
        self.assertIn('attachment; filename="rentoo-reservations-', csv_response['Content-Disposition'])

        xlsx = self.client.get(reverse('owner-export', kwargs={'entity': 'listings'}), {'type': 'xlsx'})
        self.assertEqual(xlsx.status_code, 200)
        from io import BytesIO

        from openpyxl import load_workbook

        sheet = load_workbook(BytesIO(xlsx.content)).active
        self.assertEqual(sheet.cell(row=2, column=2).value, self.item.title)
        self.assertEqual(self.client.get(reverse('owner-export', kwargs={'entity': 'secrets'})).status_code, 404)


class ReminderTests(CrmTestCase):
    def test_pickup_and_return_today(self):
        give_plan(self.owner, Plan.BUSINESS)
        manager = make_user()
        StaffMember.objects.create(owner=self.owner, user=manager, role='manager')
        StaffMember.objects.create(owner=self.owner, user=make_user(), role='viewer')
        self.reserve(2, 0, 2, client_name='Камола')
        issued_id = self.reserve(1, -3, 0).json()['id']
        Reservation.objects.filter(pk=issued_id).update(status='issued')
        self.reserve(1, 5, 6)  # не сегодня

        with mock.patch('apps.notifications.tasks.send_telegram_notification.delay'), \
                mock.patch('apps.notifications.tasks.send_web_push.delay'):
            self.assertEqual(tasks.remind_reservations(), 2)
            self.assertEqual(tasks.remind_reservations(), 0)

        titles = sorted(Notification.objects.filter(user=self.owner).values_list('payload__title', flat=True))
        self.assertEqual(titles, ['Сегодня возврат', 'Сегодня выдача'])
        self.assertEqual(Notification.objects.filter(user=manager).count(), 2)
        self.assertEqual(Notification.objects.count(), 4)


class ConcurrentReservationTests(TransactionTestCase):
    """Две брони на последние свободные единицы одновременно: проходит одна."""

    def test_parallel_reservations_for_the_last_units(self):
        owner = make_user()
        item = make_item(owner, quantity=5)
        barrier = threading.Barrier(2)
        results = [None, None]

        def worker(index):
            try:
                api = APIClient()
                api.force_authenticate(owner)
                barrier.wait()
                results[index] = api.post(reverse('owner-reservations'), {
                    'listing': item.pk, 'quantity': 3,
                    'start_date': day(1).isoformat(), 'end_date': day(2).isoformat(),
                }, format='json')
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sorted(r.status_code for r in results), [201, 409], [getattr(r, 'data', r) for r in results])
        self.assertEqual(Reservation.objects.filter(item=item).count(), 1)
        self.assertEqual(Item.objects.get(pk=item.pk).quantity, 5)

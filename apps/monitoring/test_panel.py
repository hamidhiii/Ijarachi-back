"""Админ-панель: права по разделам (смотреть / менять), действия, сотрудники, журнал."""
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.billing.models import BillingOrder, Plan, Subscription
from apps.bookings.testing import make_item, make_user
from apps.catalog.models import Item, Report
from apps.monitoring.models import MonitorAccess
from apps.monitoring.roles import ROLES
from apps.notifications.models import AuditLog

GIF = (b'GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00\xff\xff\xff,'
       b'\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02L\x01\x00;')


class PanelTests(APITestCase):
    def staff(self, role=None, **permissions):
        user = make_user()
        perms = dict(ROLES[role][1]) if role else {}
        perms.update(permissions)
        MonitorAccess.objects.create(user=user, permissions=perms)
        self.client.force_authenticate(user)
        return user

    def test_viewer_sees_but_cannot_change(self):
        item = make_item(make_user(), status=Item.STATUS_PENDING)
        self.staff('viewer')
        self.assertEqual(self.client.get(reverse('panel-listing', args=[item.pk])).status_code, 200)
        denied = self.client.post(reverse('panel-listing-moderate', args=[item.pk]), {'action': 'approve'}, format='json')
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()['code'], 'PANEL_FORBIDDEN')
        self.assertEqual(self.client.get(reverse('panel-staff')).status_code, 403)

    def test_moderator_moderates_and_resolves_reports(self):
        owner = make_user()
        item = make_item(owner, status=Item.STATUS_PENDING)
        self.staff('moderator')
        url = reverse('panel-listing-moderate', args=[item.pk])
        self.assertEqual(self.client.post(url, {'action': 'reject'}, format='json').status_code, 400)  # без причины
        self.client.post(url, {'action': 'reject', 'reason': 'Нет фото'}, format='json')
        item.refresh_from_db()
        self.assertEqual((item.status, item.rejection_reason), (Item.STATUS_REJECTED, 'Нет фото'))
        self.client.post(url, {'action': 'approve'}, format='json')
        item.refresh_from_db()
        self.assertEqual(item.status, Item.STATUS_APPROVED)

        report = Report.objects.create(item=item, reporter=make_user(), reason=Report.REASON_FRAUD)
        self.assertEqual(self.client.get(reverse('panel-reports')).json()['count'], 1)
        self.client.post(reverse('panel-report-resolve', args=[report.pk]), {'action': 'hide', 'comment': 'мошенник'},
                         format='json')
        item.refresh_from_db()
        self.assertEqual(item.status, Item.STATUS_BLOCKED)
        # Тарифы модератору не открыты.
        self.assertEqual(self.client.post(reverse('panel-user-plan', args=[owner.pk]), {'plan': 'pro'},
                                          format='json').status_code, 403)
        self.assertTrue(AuditLog.objects.filter(action='panel.listing.reject').exists())

    def test_support_blocks_finance_grants_plan_and_marks_paid(self):
        target = make_user()
        self.staff('support')
        self.client.post(reverse('panel-user-block', args=[target.pk]), {'blocked': True}, format='json')
        target.refresh_from_db()
        self.assertFalse(target.is_active)
        self.assertEqual(self.client.get(reverse('panel-user', args=[target.pk])).json()['phone'], target.phone)

        self.staff('finance')
        response = self.client.post(reverse('panel-user-plan', args=[target.pk]),
                                    {'plan': 'business', 'days': 30, 'amount': 199000}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Subscription.objects.get(user=target).plan.code, 'business')

        order = BillingOrder.objects.create(user=target, kind='plan', plan=Plan.objects.get(code='start'),
                                            amount=99000, provider='click')
        self.client.post(reverse('panel-order-action', args=[order.pk]), {'action': 'mark_paid'}, format='json')
        order.refresh_from_db()
        self.assertEqual(order.status, 'paid')

        plan = Plan.objects.get(code='start')
        self.client.patch(reverse('panel-plan', args=[plan.pk]), {'price': 120000, 'crm': True}, format='json')
        plan.refresh_from_db()
        self.assertEqual(int(plan.price), 120000)

    def test_staff_management_and_login(self):
        admin = self.staff('admin')
        response = self.client.post(reverse('panel-staff'), {
            'phone': '+998901112233', 'name': 'Азиз', 'password': 'Strong-pass-2026', 'role': 'moderator',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['role'], 'moderator')
        access_id = response.json()['id']

        # Точечная правка матрицы → роль «Своя».
        perms = dict(ROLES['moderator'][1], billing='view')
        updated = self.client.patch(reverse('panel-staff-detail', args=[access_id]), {'permissions': perms}, format='json')
        self.assertEqual(updated.json()['role'], 'custom')
        # Свои права менять нельзя.
        mine = MonitorAccess.objects.get(user=admin)
        self.assertEqual(self.client.patch(reverse('panel-staff-detail', args=[mine.pk]), {'role': 'viewer'},
                                           format='json').status_code, 400)

        self.client.force_authenticate(None)
        login = self.client.post(reverse('monitor-api-login'), {'phone': '+998901112233', 'password': 'Strong-pass-2026'},
                                 format='json')
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()['me']['permissions']['billing'], 'view')

        self.client.force_authenticate(admin)
        self.client.patch(reverse('panel-staff-detail', args=[access_id]), {'active': False}, format='json')
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(reverse('monitor-api-login'),
                                          {'phone': '+998901112233', 'password': 'Strong-pass-2026'},
                                          format='json').status_code, 401)
        self.client.force_authenticate(admin)
        self.assertGreaterEqual(self.client.get(reverse('panel-audit')).json()['count'], 3)

    def test_weak_password_refused(self):
        self.staff('admin')
        response = self.client.post(reverse('panel-staff'), {'phone': '+998901112244', 'password': '123'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('password', response.json())

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_kyc_images_and_decision(self):
        from apps.users.models import PassportDocument

        person = make_user()
        doc = PassportDocument.objects.create(user=person, front_image=SimpleUploadedFile('f.gif', GIF, 'image/gif'))
        self.staff('viewer')
        rows = self.client.get(reverse('panel-kyc')).json()['results']
        self.assertEqual(rows[0]['sides'], ['front'])
        self.assertEqual(self.client.get(reverse('panel-kyc-image', args=[doc.pk, 'front'])).status_code, 200)
        self.assertEqual(self.client.post(reverse('panel-kyc-decision', args=[doc.pk]), {'action': 'approve'},
                                          format='json').status_code, 403)
        self.staff('moderator')
        self.client.post(reverse('panel-kyc-decision', args=[doc.pk]), {'action': 'approve'}, format='json')
        doc.refresh_from_db()
        self.assertEqual(doc.status, PassportDocument.STATUS_VERIFIED)


@override_settings(CRM_BOT_TOKEN='123:test', SUPPORT_TELEGRAM_CHAT_IDS='5001')
class PanelSupportTests(APITestCase):
    staff = PanelTests.staff

    def test_support_list_reply_and_close(self):
        from unittest import mock

        from apps.crm import telegram as crm_bot
        from apps.support.models import SupportMessage, SupportTelegramMessage, SupportTicket

        customer = make_user()
        ticket = SupportTicket.objects.create(user=customer, source='owner')
        SupportMessage.objects.create(ticket=ticket, text='Не могу добавить товар')

        self.staff('moderator')  # support: view
        listing = self.client.get(reverse('panel-support'), {'status': 'active'}).json()
        self.assertEqual((listing['count'], listing['waiting']), (1, 1))
        self.assertEqual(listing['results'][0]['last_text'], 'Не могу добавить товар')
        denied = self.client.post(reverse('panel-support-reply', args=[ticket.pk]), {'text': 'x'}, format='json')
        self.assertEqual(denied.status_code, 403)

        self.staff('support')  # support: edit
        with mock.patch.object(crm_bot, 'api', return_value={'message_id': 77}) as api, \
                mock.patch('apps.notifications.tasks.create_notification') as notify:
            with self.captureOnCommitCallbacks(execute=True):
                detail = self.client.post(reverse('panel-support-reply', args=[ticket.pk]),
                                          {'text': 'Откройте «Остатки» → «Добавить»'}, format='json').json()
        self.assertEqual([m['from_staff'] for m in detail['messages_list']], [False, True])
        self.assertEqual(detail['status'], 'answered')
        notify.assert_called_once()
        self.assertEqual(api.call_args[0][1]['chat_id'], 5001)
        self.assertTrue(SupportTelegramMessage.objects.filter(ticket=ticket, message_id=77).exists())

        closed = self.client.post(reverse('panel-support-status', args=[ticket.pk]), {'status': 'closed'}, format='json')
        self.assertEqual(closed.json()['status'], 'closed')
        self.assertTrue(AuditLog.objects.filter(action='panel.support.close').exists())

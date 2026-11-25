"""CRM-бот: привязка из кабинета, кнопки под бронью, /bugun, напоминания."""
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.billing.models import Plan, Subscription
from apps.billing.testing import give_plan
from apps.bookings.testing import make_item, make_user
from apps.crm import tasks
from apps.crm import telegram as bot
from apps.crm.models import CrmBotLink, Reservation, StaffMember

CHAT = 555001


def day(offset):
    return timezone.localdate() + timedelta(days=offset)


@override_settings(CRM_BOT_TOKEN='123:test', CRM_BOT_USERNAME='rentoo_crm_bot')
class CrmBotTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        give_plan(self.owner, Plan.START)
        self.item = make_item(self.owner, quantity=5)
        self.calls = []
        patcher = mock.patch.object(bot, 'api', side_effect=self._api)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _api(self, method, payload):
        self.calls.append((method, payload))
        return {'message_id': 1}

    def sent(self, method):
        return [payload for name, payload in self.calls if name == method]

    def webhook(self, update, secret=None):
        return self.client.post(
            reverse('telegram-crm-webhook'), update, format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=bot.webhook_secret() if secret is None else secret,
        )

    def link(self, user=None, chat=CHAT):
        return CrmBotLink.objects.create(user=user or self.owner, chat_id=chat)

    def reservation(self, **fields):
        fields.setdefault('start_date', day(0))
        fields.setdefault('end_date', day(2))
        fields.setdefault('quantity', 2)
        return Reservation.objects.create(owner=self.owner, item=self.item, **fields)

    def press(self, data, chat=CHAT, sender=None):
        return self.webhook({'callback_query': {
            'id': 'cb1', 'data': data, 'from': {'id': sender or chat, 'language_code': 'ru'},
            'message': {'message_id': 9, 'chat': {'id': chat, 'type': 'private'}},
        }})


class LinkingTests(CrmBotTestCase):
    def test_wrong_secret_is_404(self):
        self.assertEqual(self.webhook({}, secret='nope').status_code, 404)

    def test_invite_link_binds_the_chat_once(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(reverse('owner-telegram'))
        self.assertEqual(response.status_code, 200)
        link = response.json()['link']
        self.assertTrue(link.startswith('https://t.me/rentoo_crm_bot?start='))
        code = link.split('start=')[1]

        start = {'message': {'text': f'/start {code}', 'chat': {'id': CHAT, 'type': 'private'},
                             'from': {'id': CHAT, 'username': 'shop', 'language_code': 'ru'}}}
        self.webhook(start)
        bound = CrmBotLink.objects.get(user=self.owner)
        self.assertEqual((bound.chat_id, bound.username, bound.language), (CHAT, 'shop', 'ru'))
        self.assertTrue(self.client.get(reverse('owner-telegram')).json()['linked'])

        # Второй переход по той же ссылке — из другого чата — не сработает.
        start['message']['chat']['id'] = start['message']['from']['id'] = 777
        self.webhook(start)
        self.assertFalse(CrmBotLink.objects.filter(chat_id=777).exists())
        self.assertIn('устарела', self.sent('sendMessage')[-1]['text'])

        self.client.delete(reverse('owner-telegram'))
        self.assertFalse(CrmBotLink.objects.exists())

    @override_settings(CRM_BOT_TOKEN='')
    def test_not_configured_is_503(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(reverse('owner-telegram')).status_code, 503)


class ButtonTests(CrmBotTestCase):
    def setUp(self):
        super().setUp()
        self.link()

    def test_issue_then_return_with_damage(self):
        reservation = self.reservation()
        self.press(f'crm:iss:{reservation.pk}')
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.STATUS_ISSUED)
        edited = self.sent('editMessageText')[-1]
        self.assertIn('Выдано', edited['text'])
        buttons = [b['callback_data'] for row in edited['reply_markup']['inline_keyboard'] for b in row if 'callback_data' in b]
        self.assertIn(f'crm:ret:{reservation.pk}', buttons)

        self.press(f'crm:dmg:{reservation.pk}')
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.STATUS_RETURNED)
        self.assertIn('повреждением', reservation.notes)

    def test_pressing_twice_is_refused_and_redrawn(self):
        reservation = self.reservation(status=Reservation.STATUS_ISSUED)
        self.press(f'crm:iss:{reservation.pk}')
        self.assertTrue(self.sent('answerCallbackQuery')[-1]['show_alert'])
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.STATUS_ISSUED)

    def test_move_shifts_both_dates_extend_only_the_return(self):
        booked = self.reservation()
        self.press(f'crm:mv2:{booked.pk}')
        booked.refresh_from_db()
        self.assertEqual((booked.start_date, booked.end_date), (day(2), day(4)))

        issued = self.reservation(status=Reservation.STATUS_ISSUED, quantity=1)
        self.press(f'crm:mv1:{issued.pk}')
        issued.refresh_from_db()
        self.assertEqual((issued.start_date, issued.end_date), (day(0), day(3)))

    def test_move_into_full_days_is_refused(self):
        booked = self.reservation(quantity=3)
        self.reservation(start_date=day(7), end_date=day(9), quantity=3)
        self.press(f'crm:mv7:{booked.pk}')
        booked.refresh_from_db()
        self.assertEqual(booked.start_date, day(0))
        self.assertIn('свободно', self.sent('answerCallbackQuery')[-1]['text'])

    def test_cancel_asks_first(self):
        reservation = self.reservation()
        self.press(f'crm:can:{reservation.pk}')
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.STATUS_BOOKED)
        self.assertTrue(self.sent('editMessageReplyMarkup'))
        self.press(f'crm:cany:{reservation.pk}')
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.STATUS_CANCELLED)

    def test_strangers_and_groups_cannot_press(self):
        reservation = self.reservation()
        # Чужой чат.
        self.press(f'crm:iss:{reservation.pk}', chat=999, sender=999)
        # Группа: нажал не тот, чей чат.
        self.press(f'crm:iss:{reservation.pk}', chat=CHAT, sender=12345)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.STATUS_BOOKED)
        self.assertEqual(len(self.sent('answerCallbackQuery')), 2)

    def test_other_owners_reservation_is_refused(self):
        other = make_user()
        give_plan(other, Plan.START)
        foreign = Reservation.objects.create(
            owner=other, item=make_item(other, quantity=3), start_date=day(0), end_date=day(1),
        )
        self.press(f'crm:iss:{foreign.pk}')
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, Reservation.STATUS_BOOKED)

    def test_free_plan_cannot_use_the_bot(self):
        reservation = self.reservation()
        Subscription.objects.update(ends_at=timezone.now() - timedelta(minutes=1))
        self.press(f'crm:iss:{reservation.pk}')
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.STATUS_BOOKED)

    def test_manager_can_viewer_cannot(self):
        give_plan(self.owner, Plan.BUSINESS)
        manager, viewer = make_user(), make_user()
        StaffMember.objects.create(owner=self.owner, user=manager, role=StaffMember.ROLE_MANAGER)
        StaffMember.objects.create(owner=self.owner, user=viewer, role=StaffMember.ROLE_VIEWER)
        self.link(manager, chat=601)
        self.link(viewer, chat=602)
        reservation = self.reservation()
        self.press(f'crm:iss:{reservation.pk}', chat=602)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.STATUS_BOOKED)
        self.press(f'crm:iss:{reservation.pk}', chat=601)
        reservation.refresh_from_db()
        self.assertEqual((reservation.status, reservation.created_by), (Reservation.STATUS_ISSUED, None))


class TodayAndReminderTests(CrmBotTestCase):
    def test_bugun_sends_todays_cards(self):
        self.link()
        self.reservation()                                                          # выдать сегодня
        self.reservation(status=Reservation.STATUS_ISSUED, start_date=day(-2), end_date=day(0), quantity=1)  # вернут сегодня
        self.reservation(start_date=day(3), end_date=day(4), quantity=1)            # не сегодня
        self.webhook({'message': {'text': '/bugun', 'chat': {'id': CHAT, 'type': 'private'}, 'from': {'id': CHAT}}})
        cards = [p for p in self.sent('sendMessage') if 'reply_markup' in p]
        self.assertEqual(len(cards), 2)
        self.assertIn('Bugun berish', cards[0]['text'] + cards[1]['text'])

    def test_bugun_without_link_explains(self):
        self.webhook({'message': {'text': '/bugun', 'chat': {'id': CHAT, 'type': 'private'}, 'from': {'id': CHAT}}})
        self.assertIn('ulanmagan', self.sent('sendMessage')[-1]['text'])

    def test_morning_reminder_goes_to_the_crm_bot_with_buttons(self):
        self.link()
        self.reservation()
        with mock.patch('apps.users.telegram_bot.send_telegram_message') as otp_bot:
            self.assertEqual(tasks.remind_reservations(), 1)
        cards = [p for p in self.sent('sendMessage') if 'reply_markup' in p]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['chat_id'], CHAT)
        otp_bot.assert_not_called()

    def test_without_the_crm_bot_reminder_stays_a_notification(self):
        self.reservation()
        self.assertEqual(tasks.remind_reservations(), 1)
        self.assertFalse(self.sent('sendMessage'))


class ContactLinkTests(CrmBotTestCase):
    """«Поделиться номером» в CRM-боте связывает Telegram с аккаунтом без кабинета."""

    def contact(self, phone, sender=CHAT, owner_id=None):
        return self.webhook({'message': {
            'message_id': 3, 'chat': {'id': CHAT, 'type': 'private'},
            'from': {'id': sender, 'language_code': 'ru', 'username': 'boss'},
            'contact': {'phone_number': phone, 'user_id': sender if owner_id is None else owner_id},
        }})

    def test_start_unlinked_asks_for_the_number(self):
        self.webhook({'message': {'chat': {'id': CHAT, 'type': 'private'},
                                  'from': {'id': CHAT, 'language_code': 'ru'}, 'text': '/start'}})
        markup = self.sent('sendMessage')[-1]['reply_markup']
        self.assertTrue(markup['keyboard'][0][0]['request_contact'])

    def test_own_contact_links_existing_account(self):
        self.contact('+' + self.owner.phone.lstrip('+'))
        link = CrmBotLink.objects.get(chat_id=CHAT)
        self.assertEqual(link.user, self.owner)
        self.assertEqual(link.username, 'boss')

        from apps.users.telegram_webapp import crm_user_for
        self.assertEqual(crm_user_for(CHAT), self.owner)

    def test_new_number_creates_account(self):
        from django.contrib.auth import get_user_model

        self.contact('998901112233')
        user = get_user_model().objects.get(crm_bot_link__chat_id=CHAT)
        self.assertTrue(user.phone.endswith('901112233'))

    def test_someone_elses_contact_is_rejected(self):
        self.contact(self.owner.phone, owner_id=777)
        self.assertFalse(CrmBotLink.objects.exists())

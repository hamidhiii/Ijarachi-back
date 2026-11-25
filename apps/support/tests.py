from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.bookings.testing import make_user
from apps.crm import telegram as crm_bot
from apps.support.models import SupportMessage, SupportTicket

AGENT = 8495935656


@override_settings(CRM_BOT_TOKEN='123:test', SUPPORT_TELEGRAM_CHAT_IDS=str(AGENT))
class SupportTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.calls = []
        self.next_id = 100
        patcher = mock.patch.object(crm_bot, 'api', side_effect=self._api)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _api(self, method, payload):
        self.calls.append((method, payload))
        self.next_id += 1
        return {'message_id': self.next_id}

    def sent(self):
        return [p for m, p in self.calls if m == 'sendMessage']

    def auth(self, user):
        self.client.credentials(HTTP_X_AUTH_TOKEN=f'Bearer {RefreshToken.for_user(user).access_token}')

    def post(self, **data):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('support-messages'), data, format='json')

    def webhook(self, update):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('telegram-crm-webhook'), update, format='json',
                                    HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=crm_bot.webhook_secret())

    def reply(self, to_message_id, text, sender=AGENT):
        return self.webhook({'message': {
            'message_id': 900, 'chat': {'id': sender, 'type': 'private'},
            'from': {'id': sender, 'first_name': 'Hamidullo'}, 'text': text,
            'reply_to_message': {'message_id': to_message_id},
        }})

    def test_user_message_reaches_agent_and_reply_comes_back(self):
        user = make_user()
        self.auth(user)
        response = self.post(text='Не могу войти', source='owner')
        self.assertEqual(response.status_code, 201)
        card = self.sent()[0]
        self.assertEqual(card['chat_id'], AGENT)
        self.assertIn('Не могу войти', card['text'])
        self.assertNotIn('key', response.data['ticket'])

        with mock.patch('apps.notifications.tasks.create_notification') as notify:
            self.reply(101, 'Откройте кабинет заново')
        notify.assert_called_once()
        thread = self.client.get(reverse('support')).data['ticket']
        self.assertEqual([m['from_staff'] for m in thread['messages']], [False, True])
        self.assertEqual(thread['status'], SupportTicket.STATUS_ANSWERED)

        # Следующее сообщение — в то же обращение.
        self.post(text='Спасибо, получилось', source='owner')
        self.assertEqual(SupportTicket.objects.count(), 1)

    def test_guest_needs_phone_and_reads_by_key(self):
        self.assertEqual(self.post(text='Помогите').status_code, 400)
        response = self.post(text='Помогите', phone='+998901112233', name='Али')
        key = response.data['ticket']['key']
        self.reply(101, 'Здравствуйте!')
        thread = self.client.get(reverse('support'), HTTP_X_SUPPORT_KEY=key).data['ticket']
        self.assertEqual(thread['messages'][-1]['text'], 'Здравствуйте!')
        self.assertIsNone(self.client.get(reverse('support')).data['ticket'])

    def test_strangers_cannot_answer_and_close_starts_new(self):
        user = make_user()
        self.auth(user)
        self.post(text='Вопрос')
        self.reply(101, 'чужой ответ', sender=777)
        self.assertFalse(SupportMessage.objects.filter(from_staff=True).exists())
        self.webhook({'callback_query': {'id': 'c', 'data': 'sup:close:%d' % SupportTicket.objects.get().pk,
                                         'from': {'id': AGENT},
                                         'message': {'message_id': 101, 'chat': {'id': AGENT, 'type': 'private'}}}})
        self.assertEqual(SupportTicket.objects.get().status, SupportTicket.STATUS_CLOSED)
        self.post(text='Новый вопрос')
        self.assertEqual(SupportTicket.objects.count(), 2)

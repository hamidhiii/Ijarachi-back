"""Номера сторон в чате видны только после раскрытия контактов по сделке."""
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.bookings.testing import make_item, make_paid_booking, make_user
from apps.chat.models import Conversation, Message


class ChatPhoneVisibilityTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.renter = make_user()
        self.item = make_item(self.owner)

    def _conversation(self, deal=None):
        conversation = Conversation.objects.create(listing=self.item, deal=deal)
        conversation.participants.add(self.owner, self.renter)
        Message.objects.create(conversation=conversation, sender=self.owner, text='Здравствуйте')
        return conversation

    def _as_renter(self):
        self.client.force_authenticate(self.renter)
        conversations = self.client.get(reverse('chat-conversations')).data
        return conversations[0]

    def test_inquiry_hides_the_other_partys_phone(self):
        conversation = self._conversation()

        row = self._as_renter()
        messages = self.client.get(reverse('chat-messages', kwargs={'pk': conversation.pk})).data['results']

        self.assertEqual(row['participant_phones'], [self.renter.phone])
        self.assertIsNone(row['last_message']['sender_phone'])
        self.assertIsNone(messages[0]['sender_phone'])

    def test_own_phone_stays_visible(self):
        conversation = self._conversation()
        self.client.force_authenticate(self.owner)

        messages = self.client.get(reverse('chat-messages', kwargs={'pk': conversation.pk})).data['results']

        self.assertEqual(messages[0]['sender_phone'], self.owner.phone)

    def test_paid_deal_reveals_phones(self):
        deal = make_paid_booking(self.item, self.renter, contact_revealed_at=timezone.now())
        self._conversation(deal=deal)

        row = self._as_renter()

        self.assertEqual(sorted(row['participant_phones']), sorted([self.owner.phone, self.renter.phone]))
        self.assertEqual(row['last_message']['sender_phone'], self.owner.phone)

    def test_posting_to_someone_elses_conversation_is_404(self):
        conversation = self._conversation()
        self.client.force_authenticate(make_user())

        response = self.client.post(
            reverse('chat-messages', kwargs={'pk': conversation.pk}), {'text': 'привет'}, format='json',
        )

        self.assertEqual(response.status_code, 404)

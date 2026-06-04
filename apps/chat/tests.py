from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.bookings.models import Booking
from apps.catalog.models import Category, Item
from apps.chat.models import Conversation


class ConversationCreateGateTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(phone='+998900000001')
        self.renter = user_model.objects.create_user(phone='+998900000002')
        self.category = Category.objects.create(name='Decor', slug='decor')
        self.item = Item.objects.create(
            owner=self.owner,
            category=self.category,
            title='Table set',
            description='Rental table set',
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
        self.url = reverse('chat-conversations')

    def test_listing_based_chat_creation_is_blocked(self):
        self.client.force_authenticate(self.renter)

        response = self.client.post(self.url, {'listing_id': self.item.pk}, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'Чат открывается после оплаты сделки')

    def test_deal_chat_creation_is_blocked_before_payment(self):
        self.client.force_authenticate(self.renter)

        response = self.client.post(self.url, {'deal_id': self.booking.pk}, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'Чат открывается после оплаты сделки')

    def test_paid_deal_chat_creation_opens_conversation_for_parties(self):
        self.booking.status = Booking.STATUS_PAID
        self.booking.save(update_fields=['status'])
        self.client.force_authenticate(self.renter)

        response = self.client.post(self.url, {'deal_id': self.booking.pk}, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        conversation = Conversation.objects.get(pk=response.data['id'])
        self.assertEqual(conversation.deal, self.booking)
        self.assertCountEqual(
            conversation.participants.values_list('id', flat=True),
            [self.owner.id, self.renter.id],
        )

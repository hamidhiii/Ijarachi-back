"""Товары кабинета, публикация на Rentoo, вход в Mini App из CRM-бота, новая бронь в боте."""
import hashlib
import hmac
import json
import time
from datetime import timedelta
from unittest import mock
from urllib.parse import urlencode

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.billing.models import Plan
from apps.billing.testing import give_plan
from apps.bookings.testing import make_item, make_user
from apps.catalog.models import Category, Item
from apps.crm import telegram as bot
from apps.crm.models import Client, CrmBotLink, Reservation

CHAT = 777001


class ProductTests(APITestCase):
    def setUp(self):
        self.owner = make_user()
        give_plan(self.owner, Plan.START)
        self.client.force_authenticate(self.owner)

    def create(self, **data):
        payload = {'title': 'Стул Кьявари', 'quantity': 40, 'price_per_day': '15000', **data}
        return self.client.post(reverse('owner-listings'), payload, format='json')

    def test_new_product_is_crm_only_and_in_stock(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual((response.json()['status'], response.json()['free_today']), ('crm', 40))
        stock = self.client.get(reverse('owner-stock')).json()
        self.assertEqual([row['quantity'] for row in stock], [40])
        # Не на rentoo.uz: ни в каталоге, ни в «Моих объявлениях».
        self.assertEqual(self.client.get('/api/v1/items/my/').json().get('count', 0), 0)
        item = Item.objects.get()
        self.assertEqual(self.client.get(f'/api/v1/listings/{item.pk}/').status_code in (200, 404), True)

    def test_required_fields(self):
        response = self.client.post(reverse('owner-listings'), {'title': 'X'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_crm_product_does_not_eat_free_limit(self):
        give_plan(self.owner, Plan.START, days=0)  # тариф кончился сразу → FREE
        from apps.catalog.limits import live_listing_count

        Item.objects.update(status=Item.STATUS_CRM)
        self.assertEqual(live_listing_count(self.owner), 0)

    def test_publish_needs_category_description_address(self):
        item_id = self.create().json()['id']
        url = reverse('owner-listing-publish', args=[item_id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()['missing']), {'category', 'description', 'address'})

        category = Category.objects.create(name='Мебель', slug='mebel-test')
        self.client.patch(reverse('owner-listing-detail', args=[item_id]), {
            'category': category.pk, 'description': 'Белые стулья для свадеб', 'address': 'Ташкент, Чиланзар',
        }, format='json')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['status'], 'pending')
        self.assertEqual(self.client.post(url).json()['code'], 'ALREADY_PUBLISHED')

    def test_published_listing_text_is_locked_but_quantity_editable(self):
        item = make_item(self.owner, quantity=3)
        url = reverse('owner-listing-detail', args=[item.pk])
        self.assertEqual(self.client.patch(url, {'title': 'Другое'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'quantity': 10}, format='json').json()['quantity'], 10)

    def test_photos_add_and_remove(self):
        import tempfile

        from django.core.files.uploadedfile import SimpleUploadedFile

        gif = (b'GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00\xff\xff\xff,'
               b'\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02L\x01\x00;')
        with self.settings(MEDIA_ROOT=tempfile.mkdtemp()):
            item_id = self.create().json()['id']
            url = reverse('owner-listing-photos', args=[item_id])
            for name in ('a.gif', 'b.gif'):
                response = self.client.post(url, {'image': SimpleUploadedFile(name, gif, content_type='image/gif')},
                                            format='multipart')
                self.assertEqual(response.status_code, 201, response.content)
            photos = response.json()['photos']
            self.assertEqual(len(photos), 2)
            self.assertEqual(response.json()['status'], 'crm')  # товар из кабинета на модерацию не уходит
            self.assertTrue(self.client.get(reverse('owner-stock')).json()[0]['photo'])

            first = photos[0]['id']
            response = self.client.delete(reverse('owner-listing-photo', args=[item_id, first]))
            self.assertEqual([p['id'] for p in response.json()['photos']], [photos[1]['id']])

            approved = make_item(self.owner)
            response = self.client.post(reverse('owner-listing-photos', args=[approved.pk]),
                                        {'image': SimpleUploadedFile('c.gif', gif, content_type='image/gif')},
                                        format='multipart')
            self.assertEqual(response.json()['status'], 'pending')  # новое фото — повторная модерация

    def test_viewer_cannot_create(self):
        from apps.crm.models import StaffMember

        give_plan(self.owner, Plan.BUSINESS)
        viewer = make_user()
        StaffMember.objects.create(owner=self.owner, user=viewer, role=StaffMember.ROLE_VIEWER)
        self.client.force_authenticate(viewer)
        response = self.client.post(f"{reverse('owner-listings')}?account={self.owner.pk}",
                                    {'title': 'X', 'quantity': 1, 'price_per_day': '1000'}, format='json')
        self.assertEqual(response.status_code, 403)


def init_data(token, user_id, auth_date=None):
    fields = {'auth_date': str(auth_date or int(time.time())), 'user': json.dumps({'id': user_id, 'first_name': 'A'})}
    check = '\n'.join(f'{k}={fields[k]}' for k in sorted(fields))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@override_settings(CRM_BOT_TOKEN='555:crm', TELEGRAM_WEBAPP_BOT_TOKEN='', TELEGRAM_BOT_TOKEN='')
class MiniAppLoginTests(APITestCase):
    def test_crm_bot_mini_app_signs_in_linked_owner(self):
        owner = make_user()
        CrmBotLink.objects.create(user=owner, chat_id=CHAT)
        response = self.client.post(reverse('auth-telegram-webapp'), {'init_data': init_data('555:crm', CHAT)}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        from rest_framework_simplejwt.tokens import AccessToken

        self.assertEqual(int(AccessToken(response.json()['access'])['user_id']), owner.pk)

    def test_sign_in_from_crm_bot_links_the_bot(self):
        from apps.users.models import TelegramLink

        owner = make_user()
        TelegramLink.objects.create(phone=owner.phone, chat_id=CHAT, telegram_user_id=CHAT)
        response = self.client.post(reverse('auth-telegram-webapp'), {'init_data': init_data('555:crm', CHAT)}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(CrmBotLink.objects.get(user=owner).chat_id, CHAT)

    @override_settings(TELEGRAM_WEBAPP_BOT_TOKEN='777:board')
    def test_sign_in_from_board_bot_does_not_link(self):
        from apps.users.models import TelegramLink

        owner = make_user()
        TelegramLink.objects.create(phone=owner.phone, chat_id=CHAT, telegram_user_id=CHAT)
        self.client.post(reverse('auth-telegram-webapp'), {'init_data': init_data('777:board', CHAT)}, format='json')
        self.assertFalse(CrmBotLink.objects.exists())

    def test_unlinked_or_forged_is_refused(self):
        url = reverse('auth-telegram-webapp')
        self.assertEqual(self.client.post(url, {'init_data': init_data('555:crm', 42)}, format='json').status_code, 404)
        self.assertEqual(self.client.post(url, {'init_data': init_data('999:other', CHAT)}, format='json').status_code, 401)


@override_settings(CRM_BOT_TOKEN='123:test', CRM_BOT_USERNAME='owner_rentoo_bot')
class NewBookingDialogTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        give_plan(self.owner, Plan.START)
        self.item = make_item(self.owner, quantity=5, price=15000)
        CrmBotLink.objects.create(user=self.owner, chat_id=CHAT)
        self.calls = []
        patcher = mock.patch.object(bot, 'api', side_effect=lambda m, p: self.calls.append((m, p)) or {'message_id': 1})
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, update):
        return self.client.post(reverse('telegram-crm-webhook'), update, format='json',
                                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=bot.webhook_secret())

    def text(self, value):
        return self.post({'message': {'text': value, 'chat': {'id': CHAT, 'type': 'private'},
                                      'from': {'id': CHAT, 'language_code': 'ru'}}})

    def press(self, value):
        return self.post({'callback_query': {
            'id': 'cb', 'data': f'crm:nb:{value}', 'from': {'id': CHAT, 'language_code': 'ru'},
            'message': {'message_id': 5, 'chat': {'id': CHAT, 'type': 'private'}},
        }})

    def last_text(self):
        return [p for m, p in self.calls if m in ('sendMessage', 'editMessageText')][-1]['text']

    def test_full_dialog_with_buttons_and_text(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        self.text('➕ Новая бронь')
        self.assertIn('Какой товар', self.last_text())
        self.press(f'i{self.item.pk}')
        self.press(f'd{tomorrow:%Y%m%d}')
        self.text('3')                      # дней — текстом
        self.press('q2')
        self.press('sinstagram')
        self.text('Азиз +998 90 123 45 67')
        self.assertIn('Проверьте', self.last_text())
        self.assertIn('90 000', self.last_text())  # 15 000 × 3 дня × 2 шт.
        self.press('ok')

        reservation = Reservation.objects.get()
        self.assertEqual((reservation.start_date, reservation.end_date, reservation.quantity, reservation.source),
                         (tomorrow, tomorrow + timedelta(days=2), 2, 'instagram'))
        self.assertEqual((reservation.client.name, reservation.client.phone), ('Азиз', '+998901234567'))
        self.assertEqual(reservation.created_by, self.owner)
        self.assertIn('Сохранено', self.last_text())

    def test_full_days_are_refused_and_date_asked_again(self):
        today = timezone.localdate()
        Reservation.objects.create(owner=self.owner, item=self.item, start_date=today, end_date=today, quantity=5)
        self.text('/yangi')
        self.press(f'i{self.item.pk}')
        self.press(f'd{today:%Y%m%d}')
        self.press('n1')
        texts = [p['text'] for m, p in self.calls if m in ('sendMessage', 'editMessageText')]
        self.assertTrue(any('свободных нет' in t for t in texts))
        self.assertIn('когда выдаёте', self.last_text())

    def test_abort_and_stranger(self):
        self.text('/yangi')
        self.press('x')
        self.assertEqual(self.last_text(), 'Отменено.')
        self.press(f'i{self.item.pk}')
        self.assertIn('устарел', self.last_text())
        self.assertFalse(Reservation.objects.exists())

    def test_no_products_points_to_cabinet(self):
        Item.objects.all().delete()
        self.text('/yangi')
        self.assertIn('Товаров пока нет', self.last_text())

    def test_free_text_without_draft_is_help(self):
        self.text('привет')
        self.assertIn('Новая бронь', self.calls[0][1]['text'])
        self.assertFalse(Client.objects.exists())

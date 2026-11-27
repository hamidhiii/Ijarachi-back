"""Payme: фискальные данные чека в ответе CheckPerformTransaction."""
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.billing import payme
from apps.billing.models import BillingOrder, Plan
from apps.billing.test_plans import PAYME_KEY, payme_auth
from apps.bookings.testing import make_item, make_user

FISCAL = dict(
    PAYMENTS_MODE='live', PAYME_SECRET_KEY=PAYME_KEY,
    PAYME_FISCAL_MXIK='10305008002000000', PAYME_FISCAL_PACKAGE_CODE='1501056',
    PAYME_FISCAL_VAT_PERCENT=12,
    PAYME_FISCAL_MXIK_PROMO='10305008003000000', PAYME_FISCAL_PACKAGE_CODE_PROMO='1501057',
    BILLING_PERIOD_DAYS=30, PROMO_TOP_DAYS=7, PROMO_VIP_DAYS=30,
)


@override_settings(**FISCAL)
class PaymeFiscalDetailTests(APITestCase):
    def setUp(self):
        self.user = make_user()

    def check(self, order):
        response = self.client.post(
            reverse('billing-payme'),
            {'jsonrpc': '2.0', 'id': 1, 'method': 'CheckPerformTransaction',
             'params': {'amount': order.amount_tiyin, 'account': {'order_id': order.pk}}},
            format='json', HTTP_AUTHORIZATION=payme_auth(),
        )
        self.assertEqual(response.status_code, 200)
        return response.json()['result']

    def assert_total_matches(self, result, amount_tiyin):
        items = result['detail']['items']
        self.assertEqual(sum(item['price'] * item['count'] for item in items), amount_tiyin)

    def test_plan_receipt(self):
        order = BillingOrder.objects.create(
            user=self.user, kind=BillingOrder.KIND_PLAN, plan=Plan.objects.get(code=Plan.START),
            amount=99000, provider=BillingOrder.PROVIDER_PAYME,
        )
        result = self.check(order)
        self.assertIs(result['allow'], True)
        self.assertEqual(result['detail'], {
            'receipt_type': 0,
            'items': [{
                'title': 'Rentoo START tarifi — 1 oy',
                'price': 9900000,
                'count': 1,
                'code': '10305008002000000',
                'package_code': '1501056',
                'vat_percent': 12,
            }],
        })
        self.assert_total_matches(result, 9900000)

    def test_top_promotion_receipt_uses_promo_codes(self):
        order = BillingOrder.objects.create(
            user=self.user, kind=BillingOrder.KIND_PROMOTION, promotion=BillingOrder.PROMO_TOP,
            item=make_item(self.user), amount=30000, provider=BillingOrder.PROVIDER_PAYME,
        )
        item = self.check(order)['detail']['items'][0]
        self.assertEqual(item['title'], "Rentoo e'lonni TOPga ko'tarish — 7 kun")
        self.assertEqual((item['price'], item['count']), (3000000, 1))
        self.assertEqual((item['code'], item['package_code']), ('10305008003000000', '1501057'))

    def test_vip_promotion_receipt(self):
        order = BillingOrder.objects.create(
            user=self.user, kind=BillingOrder.KIND_PROMOTION, promotion=BillingOrder.PROMO_VIP,
            item=make_item(self.user), amount=80000, provider=BillingOrder.PROVIDER_PAYME,
        )
        result = self.check(order)
        self.assertEqual(result['detail']['items'][0]['title'], "Rentoo VIP e'lon — 30 kun")
        self.assert_total_matches(result, 8000000)

    @override_settings(PAYME_FISCAL_MXIK_PROMO='', PAYME_FISCAL_PACKAGE_CODE_PROMO='')
    def test_promo_codes_fall_back_to_main(self):
        order = BillingOrder(kind=BillingOrder.KIND_PROMOTION, promotion=BillingOrder.PROMO_TOP, amount=1)
        item = payme.receipt_detail(order)['items'][0]
        self.assertEqual((item['code'], item['package_code']), ('10305008002000000', '1501056'))

    @override_settings(BILLING_PERIOD_DAYS=90)
    def test_other_period_is_said_in_days(self):
        order = BillingOrder(kind=BillingOrder.KIND_PLAN, plan=Plan.objects.get(code=Plan.PRO), amount=1)
        self.assertEqual(payme.receipt_title(order), 'Rentoo PRO tarifi — 90 kun')

    def test_mismatched_total_is_refused(self):
        order = BillingOrder(kind=BillingOrder.KIND_PLAN, plan=Plan.objects.get(code=Plan.START), amount=99000)
        # Позиция посчитана из одной суммы, а сверяется с другой — так быть не должно.
        with mock.patch.object(BillingOrder, 'amount_tiyin', new_callable=mock.PropertyMock,
                               side_effect=[9900000, 9900001]):
            with self.assertRaises(payme.PaymeError) as caught:
                payme.receipt_detail(order)
        self.assertEqual(caught.exception.code, payme.ERR_AMOUNT)

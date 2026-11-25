"""Акция: START бесплатно каждому пользователю до конца января."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.billing.models import Plan, Subscription, SubscriptionPeriod
from apps.billing.promo import grant_everyone, promo_ends_at
from apps.billing.testing import give_plan
from apps.monitoring.access import SuperuserAccess
from apps.monitoring.metrics import overview

User = get_user_model()


def register(phone, **extra):
    return User.objects.create_user(phone=phone, **extra)


@override_settings(PROMO_FREE_PRO_UNTIL='2027-01-31')
class SignupPromoTests(TestCase):
    def test_new_user_gets_start_until_end_of_january(self):
        with self.captureOnCommitCallbacks(execute=True):
            user = register('+998901000001')
        sub = Subscription.objects.get(user=user)
        self.assertEqual(sub.plan.code, Plan.START)
        end = timezone.localtime(sub.ends_at)
        self.assertEqual((end.year, end.month, end.day, end.hour), (2027, 2, 1, 0))  # конец 31.01 по Ташкенту
        period = SubscriptionPeriod.objects.get(user=user)
        self.assertEqual((period.source, int(period.amount)), (SubscriptionPeriod.SOURCE_PROMO, 0))

    def test_staff_and_after_the_promo_get_nothing(self):
        with self.captureOnCommitCallbacks(execute=True):
            staff = register('+998901000002', is_staff=True)
        self.assertFalse(Subscription.objects.filter(user=staff).exists())
        after = promo_ends_at() + timedelta(minutes=1)
        with mock.patch('apps.billing.promo.timezone.now', return_value=after):
            with self.captureOnCommitCallbacks(execute=True):
                late = register('+998901000003')
        self.assertFalse(Subscription.objects.filter(user=late).exists())

    @override_settings(PROMO_FREE_PRO_UNTIL='')
    def test_switched_off(self):
        with self.captureOnCommitCallbacks(execute=True):
            user = register('+998901000004')
        self.assertFalse(Subscription.objects.filter(user=user).exists())

    def test_promo_is_not_paying_in_metrics(self):
        with self.captureOnCommitCallbacks(execute=True):
            register('+998901000005')
        payer = User.objects.create_user(phone='+998901000006')  # без on_commit — без подарка
        give_plan(payer, Plan.START)
        data = overview(30, SuperuserAccess())
        kpis = {k['key']: k['value'] for k in data['kpis']}
        self.assertEqual((kpis['paying'], kpis['promo'], kpis['mrr']), (1, 1, int(Plan.objects.get(code='start').price)))

    def test_paying_during_promo_continues_after_it(self):
        from apps.billing.services import extend_subscription

        with self.captureOnCommitCallbacks(execute=True):
            user = register('+998901000007')
        promo_end = Subscription.objects.get(user=user).ends_at
        extend_subscription(user, Plan.objects.get(code=Plan.START), days=30)
        self.assertEqual(Subscription.objects.get(user=user).ends_at, promo_end + timedelta(days=30))

    def test_everyone_without_paid_plan_gets_it(self):
        free = register('+998901000008')  # без on_commit — до акции
        payer = register('+998901000009')
        give_plan(payer, Plan.BUSINESS)
        paid_end = Subscription.objects.get(user=payer).ends_at
        self.assertEqual(grant_everyone(), 1)
        self.assertEqual(Subscription.objects.get(user=free).plan.code, Plan.START)
        payer_sub = Subscription.objects.get(user=payer)
        self.assertEqual((payer_sub.plan.code, payer_sub.ends_at), (Plan.BUSINESS, paid_end))
        self.assertEqual(grant_everyone(), 1)  # повтор не плодит периодов
        self.assertEqual(SubscriptionPeriod.objects.filter(user=free).count(), 1)

    def test_old_pro_gift_becomes_start(self):
        user = register('+998901000010')
        now = timezone.now()
        pro = Plan.objects.get(code=Plan.PRO)
        Subscription.objects.create(user=user, plan=pro, ends_at=now + timedelta(days=90))
        SubscriptionPeriod.objects.create(user=user, plan=pro, starts_at=now, ends_at=now + timedelta(days=90),
                                          source=SubscriptionPeriod.SOURCE_PROMO)
        grant_everyone()
        sub = Subscription.objects.get(user=user)
        self.assertEqual((sub.plan.code, sub.ends_at), (Plan.START, promo_ends_at()))
        self.assertEqual(SubscriptionPeriod.objects.get(user=user).plan.code, Plan.START)

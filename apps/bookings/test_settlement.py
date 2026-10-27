"""Залог, кошелёк и подтверждение сделки владельцем."""
import threading
from decimal import Decimal

from django.core.cache import cache
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.bookings.models import Booking, DepositOperation
from apps.bookings.settlement import settle_completed_booking
from apps.bookings.testing import make_booking, make_item, make_paid_booking, make_user
from apps.payments.models import Payment, WalletTransaction
from apps.payments.wallet import credit_wallet
from apps.users.models import Profile

# Аренда 3 дня × 100 000, комиссия 10 % → владельцу 270 000. Залог 50 000.
OWNER_RENT = Decimal('270000')
DEPOSIT = Decimal('50000')


def balance(user):
    return Profile.objects.get(user=user).wallet_balance


class DepositTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.renter = make_user()
        self.staff = make_user(is_staff=True)
        self.item = make_item(self.owner)

    def _patch_status(self, user, booking, new_status):
        self.client.force_authenticate(user)
        return self.client.patch(
            reverse('deal-status', kwargs={'pk': booking.pk}), {'status': new_status}, format='json',
        )

    def test_online_payment_holds_deposit(self):
        draft = make_booking(self.item, self.renter)
        self.client.force_authenticate(self.renter)

        response = self.client.post(reverse('deal-pay', kwargs={'pk': draft.pk}), {'provider': 'payme'}, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        draft.refresh_from_db()
        self.assertEqual(draft.status, Booking.STATUS_PAID)
        self.assertEqual(draft.deposit_status, Booking.DEPOSIT_HELD)
        self.assertEqual(
            list(draft.deposit_operations.values_list('type', 'amount')),
            [(DepositOperation.TYPE_HOLD, DEPOSIT)],
        )

    def test_successful_return_refunds_deposit_to_renter(self):
        booking = make_paid_booking(self.item, self.renter)
        Booking.objects.filter(pk=booking.pk).update(status=Booking.STATUS_RETURNED)

        with self.captureOnCommitCallbacks(execute=True):
            response = self._patch_status(self.owner, booking, 'completed')

        self.assertEqual(response.status_code, 200, response.data)
        booking.refresh_from_db()
        self.assertEqual(booking.deposit_status, Booking.DEPOSIT_REFUNDED)
        self.assertEqual(booking.escrow_status, Booking.ESCROW_RELEASED)
        self.assertEqual(balance(self.renter), DEPOSIT)
        self.assertEqual(balance(self.owner), OWNER_RENT)
        self.assertEqual(
            list(booking.deposit_operations.values_list('type', 'amount')),
            [(DepositOperation.TYPE_REFUND, DEPOSIT)],
        )
        self.assertEqual(
            set(WalletTransaction.objects.filter(booking=booking).values_list('type', 'user_id', 'amount')),
            {
                (WalletTransaction.TYPE_RENT_PAYOUT, self.owner.pk, OWNER_RENT),
                (WalletTransaction.TYPE_DEPOSIT_REFUND, self.renter.pk, DEPOSIT),
            },
        )

    def test_dispute_resolution_withholds_part_of_deposit(self):
        booking = make_paid_booking(self.item, self.renter)
        Booking.objects.filter(pk=booking.pk).update(status=Booking.STATUS_DISPUTED, escrow_status=Booking.ESCROW_FROZEN)
        self.client.force_authenticate(self.staff)

        response = self.client.post(
            reverse('deal-resolve-dispute', kwargs={'pk': booking.pk}),
            {'deposit_withheld': 20000, 'comment': 'Пятно на скатерти'}, format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.STATUS_COMPLETED)
        self.assertEqual(booking.deposit_status, Booking.DEPOSIT_PARTIALLY_WITHHELD)
        self.assertEqual(balance(self.owner), OWNER_RENT + 20000)
        self.assertEqual(balance(self.renter), Decimal('30000'))
        ops = list(booking.deposit_operations.values_list('type', 'amount', 'actor_id'))
        self.assertEqual(ops, [
            (DepositOperation.TYPE_REFUND, Decimal('30000'), self.staff.pk),
            (DepositOperation.TYPE_WITHHOLD, Decimal('20000'), self.staff.pk),
        ])
        self.assertEqual(response.data['deposit_status'], Booking.DEPOSIT_PARTIALLY_WITHHELD)
        self.assertEqual(len(response.data['deposit_operations']), 2)

    def test_dispute_resolution_can_withhold_whole_deposit(self):
        booking = make_paid_booking(self.item, self.renter)
        Booking.objects.filter(pk=booking.pk).update(status=Booking.STATUS_DISPUTED)
        self.client.force_authenticate(self.staff)

        response = self.client.post(
            reverse('deal-resolve-dispute', kwargs={'pk': booking.pk}), {'deposit_withheld': 50000}, format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        booking.refresh_from_db()
        self.assertEqual(booking.deposit_status, Booking.DEPOSIT_WITHHELD)
        self.assertEqual(balance(self.renter), 0)

    def test_dispute_resolution_rejects_more_than_deposit(self):
        booking = make_paid_booking(self.item, self.renter)
        Booking.objects.filter(pk=booking.pk).update(status=Booking.STATUS_DISPUTED)
        self.client.force_authenticate(self.staff)

        response = self.client.post(
            reverse('deal-resolve-dispute', kwargs={'pk': booking.pk}), {'deposit_withheld': 50001}, format='json',
        )

        self.assertEqual(response.status_code, 400)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.STATUS_DISPUTED)
        self.assertFalse(WalletTransaction.objects.exists())

    def test_only_staff_resolves_disputes(self):
        booking = make_paid_booking(self.item, self.renter)
        Booking.objects.filter(pk=booking.pk).update(status=Booking.STATUS_DISPUTED)
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            reverse('deal-resolve-dispute', kwargs={'pk': booking.pk}), {'deposit_withheld': 50000}, format='json',
        )

        self.assertEqual(response.status_code, 403)

    def test_cancelled_paid_deal_returns_deposit_with_the_refund(self):
        booking = make_paid_booking(self.item, self.renter)

        response = self._patch_status(self.renter, booking, 'cancelled')

        self.assertEqual(response.status_code, 200, response.data)
        booking.refresh_from_db()
        self.assertEqual(booking.deposit_status, Booking.DEPOSIT_REFUNDED)
        self.assertEqual(booking.deposit_operations.get().type, DepositOperation.TYPE_REFUND)
        # Возврат идёт вместе со всей оплатой (Transaction refund), не в кошелёк.
        self.assertFalse(WalletTransaction.objects.exists())

    def test_cash_deal_has_no_deposit_through_platform(self):
        draft = make_booking(self.item, self.renter)
        self.client.force_authenticate(self.renter)
        self.client.post(reverse('deal-pay', kwargs={'pk': draft.pk}), {'provider': 'cash'}, format='json')
        Booking.objects.filter(pk=draft.pk).update(status=Booking.STATUS_COMPLETED)

        settle_completed_booking(draft.pk)

        draft.refresh_from_db()
        self.assertEqual(draft.deposit_status, Booking.DEPOSIT_NONE)
        self.assertFalse(WalletTransaction.objects.exists())

    def test_settling_twice_pays_once(self):
        booking = make_paid_booking(self.item, self.renter, status=Booking.STATUS_COMPLETED)

        self.assertTrue(settle_completed_booking(booking.pk))
        self.assertFalse(settle_completed_booking(booking.pk))

        self.assertEqual(balance(self.owner), OWNER_RENT)
        self.assertEqual(WalletTransaction.objects.filter(booking=booking).count(), 2)


class OwnerConfirmationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = make_user()
        self.renter = make_user()
        self.item = make_item(self.owner)
        self.booking = make_booking(self.item, self.renter, status=Booking.STATUS_PENDING_PAYMENT)

    def _confirm(self):
        self.client.force_authenticate(self.owner)
        return self.client.patch(
            reverse('deal-status', kwargs={'pk': self.booking.pk}), {'status': 'confirmed'}, format='json',
        )

    def _payment(self, provider):
        return Payment.objects.create(
            booking=self.booking, provider=provider, amount=self.booking.total_price * 100,
        )

    def test_owner_cannot_confirm_unpaid_online_deal(self):
        self._payment(Payment.PROVIDER_PAYME)

        response = self._confirm()

        self.assertEqual(response.status_code, 400)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.STATUS_PENDING_PAYMENT)

    def test_owner_cannot_confirm_without_any_payment_choice(self):
        self.assertEqual(self._confirm().status_code, 400)

    def test_owner_confirms_cash_deal(self):
        self._payment(Payment.PROVIDER_CASH)

        response = self._confirm()

        self.assertEqual(response.status_code, 200, response.data)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.STATUS_PAID)

    def test_latest_payment_choice_wins(self):
        self._payment(Payment.PROVIDER_PAYME)
        self._payment(Payment.PROVIDER_CASH)

        self.assertEqual(self._confirm().status_code, 200)


class ConcurrentWalletTests(TransactionTestCase):
    def setUp(self):
        self.owner = make_user()
        self.item = make_item(self.owner)

    def _parallel(self, calls):
        barrier = threading.Barrier(len(calls))
        errors = []

        def worker(call):
            try:
                barrier.wait()
                call()
            except Exception as exc:  # собираем, чтобы тест показал причину
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(call,)) for call in calls]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return errors

    def test_parallel_credits_are_not_lost(self):
        errors = self._parallel([
            lambda: credit_wallet(self.owner, 1000, WalletTransaction.TYPE_ADJUSTMENT) for _ in range(8)
        ])

        self.assertEqual(errors, [])
        self.assertEqual(balance(self.owner), Decimal('8000'))
        self.assertEqual(WalletTransaction.objects.filter(user=self.owner).count(), 8)
        # Журнал непрерывен: каждая строка видела баланс после предыдущей.
        self.assertEqual(
            sorted(WalletTransaction.objects.values_list('balance_after', flat=True)),
            [Decimal(1000 * i) for i in range(1, 9)],
        )

    def test_parallel_release_of_one_booking_pays_once(self):
        renter = make_user()
        booking = make_paid_booking(self.item, renter, status=Booking.STATUS_COMPLETED)

        errors = self._parallel([lambda: settle_completed_booking(booking.pk) for _ in range(4)])

        self.assertEqual(errors, [])
        self.assertEqual(balance(self.owner), OWNER_RENT)
        self.assertEqual(balance(renter), DEPOSIT)
        self.assertEqual(
            WalletTransaction.objects.filter(booking=booking, type=WalletTransaction.TYPE_RENT_PAYOUT).count(), 1,
        )

    def test_parallel_release_of_different_bookings_sums_up(self):
        from datetime import date

        bookings = [
            make_paid_booking(
                self.item, make_user(), status=Booking.STATUS_COMPLETED,
                start=date(2030, month, 10), end=date(2030, month, 12),
            )
            for month in (1, 2, 3, 4)
        ]

        errors = self._parallel([lambda b=b: settle_completed_booking(b.pk) for b in bookings])

        self.assertEqual(errors, [])
        self.assertEqual(balance(self.owner), OWNER_RENT * 4)

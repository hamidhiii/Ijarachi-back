"""
Начисления во внутренний кошелёк. Единственное место, где меняется
Profile.wallet_balance: строка профиля берётся под select_for_update, сумма
прибавляется через F() в самой БД, и рядом пишется WalletTransaction.
Параллельные начисления одному человеку выстраиваются в очередь на блокировке
и не затирают друг друга.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import F

from .models import WalletTransaction


def lock_profiles(*users):
    """
    Блокирует профили сразу нескольких людей в порядке id. Если начисление
    касается двоих (владелец и арендатор), а блокировать их по очереди «как
    придётся», две сделки со встречными ролями взаимно заблокируются.
    """
    from apps.users.models import Profile

    ids = sorted({user.pk for user in users})
    for user_id in ids:
        Profile.objects.get_or_create(user_id=user_id)
    return list(Profile.objects.select_for_update().filter(user_id__in=ids).order_by('user_id'))


def credit_wallet(user, amount, type, booking=None, comment=''):
    from apps.users.models import Profile

    amount = Decimal(amount)
    if amount <= 0:
        raise ValueError('Сумма начисления должна быть больше нуля.')

    with transaction.atomic():
        lock_profiles(user)
        Profile.objects.filter(user=user).update(wallet_balance=F('wallet_balance') + amount)
        balance = Profile.objects.filter(user=user).values_list('wallet_balance', flat=True).get()
        return WalletTransaction.objects.create(
            user=user,
            type=type,
            amount=amount,
            balance_after=balance,
            booking=booking,
            comment=comment,
        )

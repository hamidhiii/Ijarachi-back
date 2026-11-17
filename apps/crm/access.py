"""
Чей кабинет открыт и что можно делать.

По умолчанию — свой аккаунт. Сотрудник открывает кабинет владельца заголовком
`X-Owner-Account: <id владельца>` (или `?account=<id>`): он должен быть в
StaffMember этого владельца, а тариф владельца — включать сотрудников
(BUSINESS и выше). Кончился тариф — доступ сотрудников приостановлен, записи
о них остаются.

Роли: owner — всё; manager — всё, кроме управления сотрудниками; viewer —
только чтение.
"""
from rest_framework import permissions, status
from rest_framework.exceptions import APIException

from apps.billing.plans import has_feature, require_feature

from .models import StaffMember

ROLE_OWNER = 'owner'
ACCOUNT_HEADER = 'HTTP_X_OWNER_ACCOUNT'


class AccessDenied(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = 'ACCESS_DENIED'

    def __init__(self, code, detail):
        super().__init__()
        self.detail = {'code': code, 'detail': detail}


def resolve_account(request):
    """(аккаунт владельца, роль) для запроса; 403 с кодом, если доступа нет."""
    raw = request.META.get(ACCOUNT_HEADER) or request.query_params.get('account')
    if not raw or str(raw) == str(request.user.pk):
        return request.user, ROLE_OWNER
    try:
        owner_id = int(raw)
    except (TypeError, ValueError):
        raise AccessDenied('NOT_STAFF', 'Нет доступа к этому кабинету.')
    member = StaffMember.objects.select_related('owner').filter(owner_id=owner_id, user=request.user).first()
    if member is None or not member.owner.is_active:
        raise AccessDenied('NOT_STAFF', 'Нет доступа к этому кабинету.')
    if not has_feature(member.owner, 'staff_access'):
        raise AccessDenied(
            'STAFF_ACCESS_SUSPENDED',
            'Тариф владельца больше не включает сотрудников — доступ приостановлен.',
        )
    return member.owner, member.role


class OwnerAccountMixin:
    """
    Для APIView кабинета: self.account — владелец, self.role — роль.
    `owner_only = True` — только сам владелец (управление сотрудниками).
    `plan_feature` — право тарифа владельца, без которого кабинет закрыт
    (403 PLAN_FEATURE_REQUIRED). CRM — с START; на FREE только объявления.
    """
    permission_classes = [permissions.IsAuthenticated]
    owner_only = False
    plan_feature = 'crm'
    # До initial() (генерация схемы API) — пустой аккаунт: queryset просто пуст.
    account = None
    role = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.account, self.role = resolve_account(request)
        if self.owner_only and self.role != ROLE_OWNER:
            raise AccessDenied('OWNER_ONLY', 'Это может только владелец аккаунта.')
        if self.plan_feature:
            require_feature(self.account, self.plan_feature)
        if request.method not in permissions.SAFE_METHODS and self.role == StaffMember.ROLE_VIEWER:
            raise AccessDenied('READ_ONLY_ROLE', 'Роль «только просмотр» не может вносить изменения.')

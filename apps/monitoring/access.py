from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.shortcuts import render
from django.urls import reverse


class SuperuserAccess:
    """
    Права суперюзера в мониторе: открыто всё, отдельная запись MonitorAccess
    ему не нужна. is_superuser включает ссылки в админку на карточках.
    """
    is_active = True
    is_superuser = True

    can_view_deals = True
    can_view_disputes = True
    can_view_kyc = True
    can_view_payments = True
    can_view_errors = True
    can_manage_access = True

    sections = ['Сделки', 'Споры', 'KYC', 'Платежи', 'Ошибки', 'Доступы']


def get_access(user):
    """Права пользователя в мониторе или None, если доступа нет."""
    if not user.is_authenticated or not user.is_active:
        return None
    if user.is_superuser:
        return SuperuserAccess()
    access = getattr(user, 'monitor_access', None)
    return access if access is not None and access.is_active else None


def monitor_required(capability=None):
    """
    Пускает в монитор только тех, у кого есть доступ, и, если указано,
    конкретный раздел. Права кладутся в request.monitor_access — шаблоны
    по ним рисуют навигацию.
    """
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            access = get_access(request.user)
            if access is None:
                return redirect_to_login(request.get_full_path(), reverse('monitor:login'))
            # Ставим до проверки раздела: страница «нет доступа» рисует ту же
            # навигацию, чтобы человек видел, куда ему можно.
            request.monitor_access = access
            if capability and not getattr(access, capability, False):
                return render(request, 'monitoring/denied.html', status=403)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator

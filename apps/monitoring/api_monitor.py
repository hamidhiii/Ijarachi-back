"""
API монитора для monitor.rentoo.uz (Next.js). Те же права, что у Django-монитора:
суперюзер видит всё, сотрудник — разделы из MonitorAccess.

    POST /api/v1/monitor/login/        {phone, password} → {access, refresh, me}
    GET  /api/v1/monitor/me/           кто я и какие разделы открыты
    GET  /api/v1/monitor/live/         онлайн сейчас, DAU/WAU/MAU, пик (каждые 15 с)
    GET  /api/v1/monitor/overview/?days=7|30|90   KPI, ряды, разбивки, последние события
    GET  /api/v1/monitor/checks/       проблемы: деньги, застрявшие сделки, KYC
    GET  /api/v1/monitor/funnel/?days= воронка входа
    GET  /api/v1/monitor/users/?q=&plan=&page=
    GET  /api/v1/monitor/listings/?q=&status=&page=
    GET  /api/v1/monitor/deals/?status=&page=
    GET  /api/v1/monitor/orders/?status=&page=     (раздел «Платежи»)
"""
from django.contrib.auth import authenticate, get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from . import checks, metrics, presence
from .access import get_access

User = get_user_model()
PAGE = 25
def _me(user, access):
    from .roles import ROLES, SECTIONS, normalize

    profile = getattr(user, 'profile', None)
    permissions = access.permissions if access.is_superuser else normalize(access.permissions)
    return {
        'id': user.pk, 'phone': user.phone, 'name': getattr(profile, 'full_name', '') or '',
        'superuser': bool(access.is_superuser),
        'role': access.role, 'role_label': 'Суперюзер' if access.is_superuser else ROLES.get(access.role, ('Своя',))[0],
        'permissions': permissions,
        'sections': [{'key': key, 'label': label, 'hint': hint} for key, label, hint in SECTIONS],
    }


class MonitorPermission(permissions.BasePermission):
    """
    Раздел вью (`section`) и метод решают: GET — нужен уровень view, остальное — edit.
    `edit_section` — когда менять разрешает другой раздел (тариф из карточки пользователя).
    """

    def has_permission(self, request, view):
        from .roles import RANK

        if not request.user or not request.user.is_authenticated:
            return False
        access = get_access(request.user)
        if access is None:
            return False
        request.monitor_access = access
        section = getattr(view, 'section', None)
        if not section:
            return True
        write = request.method not in permissions.SAFE_METHODS
        if write:
            section = getattr(view, 'edit_section', None) or section
        need = 2 if write else 1
        if RANK[access.level(section)] < need:
            raise PermissionDenied({
                'code': 'PANEL_FORBIDDEN',
                'detail': 'Недостаточно прав: ' + ('менять' if write else 'смотреть') + ' этот раздел вам не разрешено.',
                'section': section,
            })
        return True


class MonitorView(APIView):
    permission_classes = [MonitorPermission]
    section = None


def can(request, section, level='view'):
    from .roles import RANK

    return RANK[request.monitor_access.level(section)] >= RANK[level]


def _days(request, default=7):
    try:
        value = int(request.query_params.get('days', default))
    except (TypeError, ValueError):
        value = default
    return min(max(value, 1), 365)


def _page_number(request):
    try:
        return max(int(request.query_params.get('page', 1)), 1)
    except (TypeError, ValueError):
        return 1


def _offset(request):
    return (_page_number(request) - 1) * PAGE


def _page(request, qs, row):
    page = _page_number(request)
    total = qs.count()
    items = qs[(page - 1) * PAGE: page * PAGE]
    return Response({'count': total, 'page': page, 'pages': max((total + PAGE - 1) // PAGE, 1),
                     'results': [row(obj) for obj in items]})


class LoginView(APIView):
    authentication_classes = []
    permission_classes = []
    throttle_scope = 'auth'

    def post(self, request):
        phone = str(request.data.get('phone') or '').strip()
        password = str(request.data.get('password') or '')
        user = authenticate(request, username=phone, password=password) if phone and password else None
        access = get_access(user) if user else None
        if access is None:
            return Response({'code': 'MONITOR_LOGIN_FAILED',
                             'detail': 'Неверный телефон или пароль, или нет доступа к монитору.'},
                            status=status.HTTP_401_UNAUTHORIZED)
        refresh = RefreshToken.for_user(user)
        return Response({'access': str(refresh.access_token), 'refresh': str(refresh), 'me': _me(user, access)})


class MeView(MonitorView):
    def get(self, request):
        return Response(_me(request.user, request.monitor_access))


class LiveView(MonitorView):
    section = 'analytics'

    def get(self, request):
        return Response(presence.live())


class OverviewView(MonitorView):
    section = 'analytics'

    def get(self, request):
        return Response(metrics.overview(_days(request), request.monitor_access))


class ChecksView(MonitorView):
    section = 'analytics'

    def get(self, request):
        result = []
        for check in checks.run_checks():
            result.append({
                'code': check.code, 'title': check.title, 'hint': check.hint, 'severity': check.severity,
                'total': check.total,
                'issues': [{'label': i.label, 'detail': i.detail, 'url': i.url} for i in check.issues[:20]],
            })
        stuck = [
            {'id': s.booking.pk, 'label': s.booking.item.title if s.booking.item_id else f'Сделка #{s.booking.pk}',
             'status': s.booking.get_status_display(), 'reason': s.reason, 'hours': s.age_hours}
            for s in checks.stuck_deals()[:30]
        ]
        return Response({'checks': result, 'stuck': stuck})


class FunnelView(MonitorView):
    section = 'analytics'

    def get(self, request):
        data = metrics.auth_funnel(_days(request))
        for key in ('code_not_entered', 'never_got_code', 'recent_failures'):
            for row in data[key]:
                row['at'] = row['at'].isoformat() if row.get('at') else None
        data['funnel'] = [{'label': label, 'value': value} for label, value in data['funnel']]
        return Response(data)


class UsersView(MonitorView):
    section = 'users'

    def get(self, request):
        from apps.billing.models import Subscription

        qs = User.objects.select_related('profile').order_by('-date_joined')
        q = request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(Q(phone__icontains=q) | Q(profile__full_name__icontains=q) | Q(profile__shop_name__icontains=q))
        plan = request.query_params.get('plan')
        now = timezone.now()
        if plan == 'free':
            qs = qs.exclude(subscription__ends_at__gt=now)
        elif plan:
            qs = qs.filter(subscription__plan__code=plan, subscription__ends_at__gt=now)
        subs = {}

        def row(user):
            profile = getattr(user, 'profile', None)
            if user.pk not in subs:
                sub = Subscription.objects.select_related('plan').filter(user=user, ends_at__gt=now).first()
                subs[user.pk] = sub
            sub = subs[user.pk]
            return {
                'id': user.pk, 'phone': user.phone, 'name': getattr(profile, 'full_name', '') or '',
                'shop': getattr(profile, 'shop_name', '') or '',
                'type': getattr(profile, 'account_type', ''), 'verified': bool(getattr(profile, 'is_verified_kyc', False)),
                'plan': sub.plan.code if sub else 'free', 'plan_until': sub.ends_at.isoformat() if sub else None,
                'listings': user.items.exclude(status='crm').count(),
                'joined': user.date_joined.isoformat(),
                'last_login': user.last_login.isoformat() if user.last_login else None,
                'last_seen': seen[user.pk].isoformat() if user.pk in seen else None,
                'active': user.is_active,
            }

        page_ids = list(qs.values_list('pk', flat=True)[_offset(request): _offset(request) + PAGE])
        seen = presence.last_seen(page_ids)
        return _page(request, qs, row)


class ListingsView(MonitorView):
    section = 'listings'

    def get(self, request):
        from apps.catalog.models import Item

        qs = Item.objects.select_related('owner', 'category').order_by('-created_at')
        q = request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(owner__phone__icontains=q))
        if request.query_params.get('status'):
            qs = qs.filter(status=request.query_params['status'])
        return _page(request, qs, lambda i: {
            'id': i.pk, 'title': i.title, 'status': i.status, 'status_label': i.get_status_display(),
            'category': i.category.name if i.category_id else '', 'price': int(i.price_per_day),
            'quantity': i.quantity, 'views': i.view_count, 'owner': i.owner.phone, 'city': i.city,
            'at': i.created_at.isoformat(),
        })


class DealsView(MonitorView):
    section = 'deals'

    def get(self, request):
        from apps.bookings.models import Booking

        qs = Booking.objects.exclude(status=Booking.STATUS_DRAFT).select_related('item', 'renter').order_by('-created_at')
        if request.query_params.get('status'):
            qs = qs.filter(status=request.query_params['status'])
        money = can(request, 'payments')
        return _page(request, qs, lambda b: {
            'id': b.pk, 'title': b.item.title if b.item_id else '—', 'renter': b.renter.phone if b.renter_id else '',
            'status': b.status, 'status_label': b.get_status_display(),
            'from': b.start_date.isoformat(), 'to': b.end_date.isoformat(),
            'total': int(b.total_price) if money else None, 'escrow': b.escrow_status,
            'at': b.created_at.isoformat(),
        })


class OrdersView(MonitorView):
    section = 'payments'

    def get(self, request):
        from apps.billing.models import BillingOrder

        qs = BillingOrder.objects.select_related('user', 'plan', 'item').order_by('-created_at')
        if request.query_params.get('status'):
            qs = qs.filter(status=request.query_params['status'])
        return _page(request, qs, lambda o: {
            'id': o.pk, 'user': o.user.phone, 'kind': o.kind, 'title': o.title, 'amount': int(o.amount),
            'provider': o.provider, 'status': o.status, 'status_label': o.get_status_display(),
            'attention': o.needs_attention, 'at': o.created_at.isoformat(),
            'paid_at': o.paid_at.isoformat() if o.paid_at else None,
        })

"""
API кабинета владельца (owner.rentoo.uz): /api/v1/owner/...

Каждый запрос работает в аккаунте владельца — своём или, для сотрудника, в
том, что указан в X-Owner-Account (apps.crm.access). Права тарифа проверяются
по тарифу владельца аккаунта, а не сотрудника.
"""
from datetime import date, timedelta

from django.db.models import Count, Max, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.plans import current_plan, require_feature
from apps.bookings.availability import _days, manual_blocked_dates, units_by_day
from apps.catalog.models import Item

from .access import ROLE_OWNER, OwnerAccountMixin
from .models import Branch, Client, Reservation, StaffMember
from .serializers import (
    AccountSerializer,
    BranchSerializer,
    ClientDetailSerializer,
    ClientSerializer,
    ListingCalendarSerializer,
    OwnerListingSerializer,
    ReservationSerializer,
    StaffMemberSerializer,
    StaffRoleSerializer,
    StatsResponseSerializer,
    StockRowSerializer,
)
from .services import CrmError, date_range, free_units, save_reservation

ACCOUNT_PARAM = OpenApiParameter(
    'X-Owner-Account', location=OpenApiParameter.HEADER, required=False, type=int,
    description='Кабинет какого владельца открыт (для сотрудника). Без заголовка — свой.',
)


def _parse_day(value, default):
    if not value:
        return default
    parsed = parse_date(value)
    if parsed is None:
        raise CrmError('INVALID_DATES', f'Неверная дата: {value}. Формат YYYY-MM-DD.')
    return parsed


class AccountsView(OwnerAccountMixin, APIView):
    """GET /owner/accounts/ — кабинеты, доступные мне: свой и где я сотрудник."""

    @extend_schema(responses=AccountSerializer(many=True))
    def get(self, request):
        def name(user):
            profile = getattr(user, 'profile', None)
            return (profile and (profile.shop_name or profile.full_name)) or user.phone

        rows = [{'id': request.user.pk, 'name': name(request.user), 'role': ROLE_OWNER, 'plan': current_plan(request.user).code}]
        for member in StaffMember.objects.filter(user=request.user).select_related('owner__profile'):
            rows.append({'id': member.owner_id, 'name': name(member.owner), 'role': member.role, 'plan': current_plan(member.owner).code})
        return Response(AccountSerializer(rows, many=True).data)


# ─── Сотрудники (BUSINESS+) и точки (PRO) ────────────────────────────────────

class StaffListCreateView(OwnerAccountMixin, generics.ListCreateAPIView):
    """GET/POST /owner/staff/ — сотрудники; добавлять может только владелец на тарифе BUSINESS+."""
    owner_only = True
    serializer_class = StaffMemberSerializer
    pagination_class = None

    def get_queryset(self):
        return StaffMember.objects.filter(owner=self.account).select_related('user__profile')

    def perform_create(self, serializer):
        require_feature(self.account, 'staff_access')
        user = serializer.validated_data.pop('phone')
        if user.pk == self.account.pk:
            raise CrmError('STAFF_SELF', 'Владелец уже имеет полный доступ.')
        if StaffMember.objects.filter(owner=self.account, user=user).exists():
            raise CrmError('STAFF_EXISTS', 'Этот пользователь уже сотрудник.')
        serializer.save(owner=self.account, user=user)


class StaffDetailView(OwnerAccountMixin, generics.UpdateAPIView, generics.DestroyAPIView):
    """PATCH/DELETE /owner/staff/{id}/ — сменить роль или убрать сотрудника."""
    owner_only = True
    serializer_class = StaffRoleSerializer
    http_method_names = ['patch', 'delete']

    def get_queryset(self):
        return StaffMember.objects.filter(owner=self.account)


class BranchListCreateView(OwnerAccountMixin, generics.ListCreateAPIView):
    """GET/POST /owner/branches/ — точки проката (создание — тариф PRO)."""
    serializer_class = BranchSerializer
    pagination_class = None

    def get_queryset(self):
        return Branch.objects.filter(owner=self.account).annotate(listings_count=Count('items'))

    def perform_create(self, serializer):
        require_feature(self.account, 'branches')
        serializer.save(owner=self.account)


class BranchDetailView(OwnerAccountMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = BranchSerializer

    def get_queryset(self):
        return Branch.objects.filter(owner=self.account).annotate(listings_count=Count('items'))

    def perform_update(self, serializer):
        require_feature(self.account, 'branches')
        serializer.save()


# ─── Объявления, календарь, остатки ──────────────────────────────────────────

class OwnerListingsView(OwnerAccountMixin, generics.ListAPIView):
    """GET /owner/listings/?branch= — объявления аккаунта с количеством и свободным сегодня."""
    serializer_class = OwnerListingSerializer
    pagination_class = None

    def get_queryset(self):
        qs = Item.objects.filter(owner=self.account).order_by('title', 'pk')
        branch = self.request.query_params.get('branch')
        if branch:
            qs = qs.filter(branch_id=branch)
        return qs

    def list(self, request, *args, **kwargs):
        today = timezone.localdate()
        items = list(self.get_queryset())
        for item in items:
            item.free_today = free_units(item, today, today)
        return Response(OwnerListingSerializer(items, many=True, context={'account': self.account}).data)


class OwnerListingDetailView(OwnerAccountMixin, generics.UpdateAPIView):
    """PATCH /owner/listings/{id}/ {"branch": id|null} — привязать объявление к точке (PRO)."""
    serializer_class = OwnerListingSerializer
    http_method_names = ['patch']

    def get_queryset(self):
        return Item.objects.filter(owner=self.account)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'account': self.account}

    def perform_update(self, serializer):
        if serializer.validated_data.get('branch') is not None:
            require_feature(self.account, 'branches')
        item = serializer.save()
        today = timezone.localdate()
        item.free_today = free_units(item, today, today)


class ListingCalendarView(OwnerAccountMixin, APIView):
    """
    GET /owner/listings/{id}/calendar/?from=&to= — по дням: занято, свободно,
    закрыто вручную; и брони за период. По умолчанию — 30 дней с сегодня, до 92.
    """

    @extend_schema(parameters=[ACCOUNT_PARAM], responses=ListingCalendarSerializer)
    def get(self, request, pk):
        item = Item.objects.filter(owner=self.account, pk=pk).first()
        if item is None:
            raise NotFound('Объявление не найдено.')
        today = timezone.localdate()
        start = _parse_day(request.query_params.get('from'), today)
        end = _parse_day(request.query_params.get('to'), start + timedelta(days=29))
        days = date_range(start, end)
        counts = units_by_day(item, start, end)
        manual = set(manual_blocked_dates(item))
        reservations = (
            Reservation.objects.filter(item=item, start_date__lte=end, end_date__gte=start)
            .exclude(status=Reservation.STATUS_CANCELLED).select_related('client', 'item')
        )
        return Response({
            'listing': item.pk,
            'title': item.title,
            'quantity': item.quantity,
            'days': [
                {
                    'date': day,
                    'booked': counts.get(day, 0),
                    'free': 0 if day.isoformat() in manual else max(item.quantity - counts.get(day, 0), 0),
                    'blocked': day.isoformat() in manual,
                }
                for day in days
            ],
            'reservations': ReservationSerializer(reservations, many=True).data,
        })


class StockView(OwnerAccountMixin, APIView):
    """
    GET /owner/stock/?date= или ?from=&to=[&branch=] — остатки: свободно =
    количество − забронировано (на период — по самому загруженному дню).
    """

    @extend_schema(parameters=[ACCOUNT_PARAM], responses=StockRowSerializer(many=True))
    def get(self, request):
        today = timezone.localdate()
        day = _parse_day(request.query_params.get('date'), None)
        start = day or _parse_day(request.query_params.get('from'), today)
        end = day or _parse_day(request.query_params.get('to'), start)
        date_range(start, end, limit_days=366)
        items = Item.objects.filter(owner=self.account).exclude(status=Item.STATUS_REJECTED).order_by('title', 'pk')
        if request.query_params.get('branch'):
            items = items.filter(branch_id=request.query_params['branch'])
        rows = []
        for item in items:
            free = free_units(item, start, end)
            rows.append({
                'id': item.pk, 'title': item.title, 'branch': item.branch_id,
                'quantity': item.quantity, 'booked': item.quantity - free, 'free': free,
            })
        return Response(StockRowSerializer(rows, many=True).data)


# ─── Брони и клиенты ─────────────────────────────────────────────────────────

class ReservationListCreateView(OwnerAccountMixin, generics.ListCreateAPIView):
    """
    GET  /owner/reservations/?from=&to=&listing=&status=&branch=&client=
    POST /owner/reservations/ — ручная бронь (источник: rentoo/instagram/phone/other).
    Не хватает свободных единиц на какой-то день — 409 `NOT_ENOUGH_STOCK` с `free`.
    """
    serializer_class = ReservationSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'account': self.account}

    def get_queryset(self):
        qs = Reservation.objects.filter(owner=self.account).select_related('item', 'client')
        params = self.request.query_params
        if params.get('from'):
            qs = qs.filter(end_date__gte=_parse_day(params['from'], None))
        if params.get('to'):
            qs = qs.filter(start_date__lte=_parse_day(params['to'], None))
        for param, field in (('listing', 'item_id'), ('status', 'status'), ('branch', 'item__branch_id'), ('client', 'client_id')):
            if params.get(param):
                qs = qs.filter(**{field: params[param]})
        return qs

    def perform_create(self, serializer):
        serializer.instance = save_reservation(self.account, serializer.validated_data, actor=self.request.user)


class ReservationDetailView(OwnerAccountMixin, generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PATCH /owner/reservations/{id}/ — изменить даты, количество, клиента или
    статус (booked → issued → returned, отмена — cancelled). DELETE — отмена.
    """
    serializer_class = ReservationSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'account': self.account}

    def get_queryset(self):
        return Reservation.objects.filter(owner=self.account).select_related('item', 'client')

    def perform_update(self, serializer):
        serializer.instance = save_reservation(
            self.account, serializer.validated_data, instance=serializer.instance, actor=self.request.user,
        )

    def destroy(self, request, *args, **kwargs):
        reservation = self.get_object()
        if reservation.status in Reservation.OCCUPYING_STATUSES:
            save_reservation(self.account, {'status': Reservation.STATUS_CANCELLED}, instance=reservation)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ClientListCreateView(OwnerAccountMixin, generics.ListCreateAPIView):
    """GET /owner/clients/?q= — база клиентов (поиск по имени и телефону); POST — новый клиент."""
    serializer_class = ClientSerializer

    def get_queryset(self):
        qs = Client.objects.filter(owner=self.account).annotate(
            reservations_count=Count('reservations', filter=~Q(reservations__status=Reservation.STATUS_CANCELLED)),
            last_reservation=Max('reservations__start_date'),
        )
        query = self.request.query_params.get('q')
        if query:
            qs = qs.filter(Q(name__icontains=query) | Q(phone__icontains=query))
        return qs

    def perform_create(self, serializer):
        from django.contrib.auth import get_user_model

        phone = serializer.validated_data.get('phone', '').strip()
        if phone and Client.objects.filter(owner=self.account, phone=phone).exists():
            raise CrmError('CLIENT_EXISTS', 'Клиент с этим номером уже есть в базе.')
        rentoo_user = get_user_model().objects.filter(phone=phone).first() if phone else None
        serializer.save(owner=self.account, phone=phone, user=rentoo_user)


class ClientDetailView(OwnerAccountMixin, generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /owner/clients/{id}/ — карточка клиента с историей аренд."""
    serializer_class = ClientDetailSerializer

    def get_queryset(self):
        return Client.objects.filter(owner=self.account).annotate(
            reservations_count=Count('reservations', filter=~Q(reservations__status=Reservation.STATUS_CANCELLED)),
            last_reservation=Max('reservations__start_date'),
        )


# ─── Статистика (BUSINESS+) и выгрузка (PRO) ─────────────────────────────────

def _month_bounds(value):
    today = timezone.localdate()
    if value:
        try:
            year, month = (int(part) for part in value.split('-'))
            first = date(year, month, 1)
        except ValueError:
            raise CrmError('INVALID_DATES', 'Месяц в формате YYYY-MM.')
    else:
        first = today.replace(day=1)
    following = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, following - timedelta(days=1)


class StatsView(OwnerAccountMixin, APIView):
    """
    GET /owner/stats/?month=YYYY-MM — по каждому объявлению за месяц: просмотры,
    показы номера (без дублей за 24 ч и без владельца), сообщения в чате от
    арендаторов; итоги и помесячная динамика за 6 месяцев. Тариф BUSINESS+.
    """

    @extend_schema(parameters=[ACCOUNT_PARAM, OpenApiParameter('month', str)], responses=StatsResponseSerializer)
    def get(self, request):
        from .stats import listing_stats, monthly_totals

        require_feature(self.account, 'statistics')
        first, last = _month_bounds(request.query_params.get('month'))
        rows = listing_stats(self.account, first, last)
        totals = {key: sum(row[key] for row in rows) for key in ('views', 'phone_reveals', 'chat_messages')}
        totals['listings'] = len(rows)
        return Response({
            'month': first.strftime('%Y-%m'),
            'totals': totals,
            'listings': rows,
            'by_month': monthly_totals(self.account, first, months=6),
        })


class ExportView(OwnerAccountMixin, APIView):
    """
    GET /owner/export/{listings|reservations|clients}/?type=csv|xlsx —
    выгрузка данных аккаунта. Тариф PRO. Параметр не `format`: его DRF забирает
    себе под выбор рендерера.
    """

    @extend_schema(
        parameters=[ACCOUNT_PARAM, OpenApiParameter('type', str, enum=['csv', 'xlsx'])],
        responses={(200, 'application/octet-stream'): bytes},
    )
    def get(self, request, entity):
        from .export import ENTITIES, render

        require_feature(self.account, 'data_export')
        if entity not in ENTITIES:
            raise NotFound('Неизвестная выгрузка.')
        fmt = request.query_params.get('type', 'xlsx')
        if fmt not in ('csv', 'xlsx'):
            raise CrmError('INVALID_FORMAT', 'Формат выгрузки: csv или xlsx.')
        return render(self.account, entity, fmt)

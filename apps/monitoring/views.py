from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from apps.bookings.models import Booking
from apps.payments.models import Payment, Transaction
from apps.users.models import FaceVerification, KYCDocument, PassportDocument

from . import checks
from .access import get_access, monitor_required
from .forms import GrantAccessForm, MonitorAccessForm, MonitorLoginForm, MonitorUserCreateForm
from .models import MonitorAccess

User = get_user_model()

PAGE_SIZE = 50


class MonitorLoginView(LoginView):
    """Отдельный вход в монитор: сессия общая с сайтом, но /admin/ здесь ни при чём."""
    template_name = 'monitoring/login.html'
    authentication_form = MonitorLoginForm
    redirect_authenticated_user = False

    def get_success_url(self):
        return self.get_redirect_url() or reverse('monitor:index')

    def form_valid(self, form):
        if get_access(form.get_user()) is None:
            form.add_error(None, 'У этой учётной записи нет доступа к монитору.')
            return self.form_invalid(form)
        return super().form_valid(form)


def monitor_logout(request):
    logout(request)
    return redirect('monitor:login')


@monitor_required()
def index(request):
    access = request.monitor_access
    now = timezone.now()
    month_ago = now - timedelta(days=30)

    by_status = {
        row['status']: row['total']
        for row in Booking.objects.values('status').annotate(total=Count('id'))
    }
    status_rows = [
        {'code': code, 'label': label, 'total': by_status.get(code, 0)}
        for code, label in Booking.STATUS_CHOICES
    ]

    context = {
        'status_rows': status_rows,
        'deals_total': sum(by_status.values()),
        'deals_new': Booking.objects.filter(created_at__gte=month_ago).count(),
        'stuck_total': len(checks.stuck_deals()) if access.can_view_errors or access.can_view_deals else 0,
        'disputes_total': by_status.get(Booking.STATUS_DISPUTED, 0),
        'kyc_pending': PassportDocument.objects.filter(status=PassportDocument.STATUS_PENDING).count(),
        'payments_failed': Payment.objects.filter(
            status=Payment.STATUS_FAILED, created_at__gte=month_ago
        ).count(),
        'escrow_held': Booking.objects.filter(escrow_status=Booking.ESCROW_HELD).aggregate(
            total=Sum('escrow_amount')
        )['total'] or 0,
        'checks': checks.run_checks() if access.can_view_errors else [],
    }
    return render(request, 'monitoring/index.html', context)


@monitor_required('can_view_deals')
def deals(request):
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()

    queryset = Booking.objects.select_related('item', 'item__owner', 'renter').order_by('-created_at')
    if status:
        queryset = queryset.filter(status=status)
    if query:
        criteria = Q(item__title__icontains=query) | Q(renter__phone__icontains=query) | Q(item__owner__phone__icontains=query)
        if query.lstrip('#').isdigit():
            criteria |= Q(pk=int(query.lstrip('#')))
        queryset = queryset.filter(criteria)

    page = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'monitoring/deals.html', {
        'page': page,
        'query': query,
        'status': status,
        'status_choices': Booking.STATUS_CHOICES,
    })


@monitor_required('can_view_deals')
def deal_detail(request, pk):
    booking = get_object_or_404(
        Booking.objects.select_related('item', 'item__owner', 'renter', 'renter__profile', 'item__owner__profile'),
        pk=pk,
    )
    access = request.monitor_access

    payments = booking.payments.order_by('-created_at') if access.can_view_payments else None
    transactions = (
        Transaction.objects.filter(booking=booking).select_related('user').order_by('-created_at')
        if access.can_view_payments else None
    )

    return render(request, 'monitoring/deal_detail.html', {
        'booking': booking,
        'logs': booking.status_logs.order_by('-created_at'),
        'payments': payments,
        'transactions': transactions,
        'photos': booking.photos.select_related('uploaded_by'),
        'conversations': booking.conversations.annotate(message_count=Count('messages')),
        'progress_renter': booking.progress_for('renter'),
        'progress_owner': booking.progress_for('owner'),
    })


@monitor_required('can_view_deals')
def stuck(request):
    return render(request, 'monitoring/stuck.html', {'stuck_deals': checks.stuck_deals()})


@monitor_required('can_view_disputes')
def disputes(request):
    queryset = (
        Booking.objects
        .filter(status=Booking.STATUS_DISPUTED)
        .select_related('item', 'item__owner', 'renter')
        .order_by('updated_at')
    )
    page = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'monitoring/disputes.html', {'page': page})


@monitor_required('can_view_kyc')
def kyc(request):
    status = request.GET.get('status', PassportDocument.STATUS_PENDING)

    passports = PassportDocument.objects.select_related('user').order_by('submitted_at')
    if status:
        passports = passports.filter(status=status)

    return render(request, 'monitoring/kyc.html', {
        'page': Paginator(passports, PAGE_SIZE).get_page(request.GET.get('page')),
        'status': status,
        'status_choices': PassportDocument.STATUS_CHOICES,
        'faces': FaceVerification.objects.select_related('user').exclude(
            status=FaceVerification.STATUS_PASSED
        ).order_by('-submitted_at')[:PAGE_SIZE],
        'legacy_pending': KYCDocument.objects.filter(
            status=KYCDocument.STATUS_PENDING
        ).select_related('user').order_by('submitted_at')[:PAGE_SIZE],
    })


@monitor_required('can_view_payments')
def payments(request):
    status = request.GET.get('status', '').strip()
    provider = request.GET.get('provider', '').strip()

    queryset = Payment.objects.select_related('booking', 'booking__item').order_by('-created_at')
    if status:
        queryset = queryset.filter(status=status)
    if provider:
        queryset = queryset.filter(provider=provider)

    page = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'monitoring/payments.html', {
        'page': page,
        'status': status,
        'provider': provider,
        'status_choices': Payment.STATUS_CHOICES,
        'provider_choices': Payment.PROVIDER_CHOICES,
        'transactions': Transaction.objects.select_related('user', 'booking').order_by('-created_at')[:PAGE_SIZE],
    })


@monitor_required('can_view_errors')
def errors(request):
    return render(request, 'monitoring/errors.html', {
        'checks': checks.run_checks(),
        'stuck_total': len(checks.stuck_deals()),
    })


@monitor_required('can_manage_access')
def access_list(request):
    return render(request, 'monitoring/access_list.html', {
        'accesses': MonitorAccess.objects.select_related('user', 'created_by').all(),
        'superusers': User.objects.filter(is_superuser=True).order_by('phone'),
    })


@monitor_required('can_manage_access')
def access_create(request):
    """Завести нового сотрудника или выдать доступ уже существующему пользователю."""
    mode = request.GET.get('mode', 'new')
    form_class = MonitorUserCreateForm if mode == 'new' else GrantAccessForm

    if request.method == 'POST':
        form = form_class(request.POST)
        if form.is_valid():
            access = form.save(created_by=request.user)
            messages.success(request, f'Доступ выдан: {access.user.phone}')
            return redirect('monitor:access_list')
    else:
        form = form_class()

    return render(request, 'monitoring/access_form.html', {
        'form': form,
        'mode': mode,
        'title': 'Новый сотрудник' if mode == 'new' else 'Доступ существующему пользователю',
    })


@monitor_required('can_manage_access')
def access_edit(request, pk):
    access = get_object_or_404(MonitorAccess.objects.select_related('user'), pk=pk)

    if request.method == 'POST':
        if 'delete' in request.POST:
            phone = access.user.phone
            access.delete()
            messages.success(request, f'Доступ отозван: {phone}')
            return redirect('monitor:access_list')
        form = MonitorAccessForm(request.POST, instance=access)
        if form.is_valid():
            form.save()
            messages.success(request, 'Сохранено')
            return redirect('monitor:access_list')
    else:
        form = MonitorAccessForm(instance=access)

    return render(request, 'monitoring/access_form.html', {
        'form': form,
        'access': access,
        'title': f'Доступ: {access.user.phone}',
    })
